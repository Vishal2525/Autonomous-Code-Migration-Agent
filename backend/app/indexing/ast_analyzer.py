"""Deterministic Python source analysis via the stdlib ``ast`` module.

No LLM involved: imports, symbols, decorators, routes, and local-file
dependency resolution are all computed exactly.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path
from typing import Any

ROUTE_DECORATOR_ATTRS = {"route", "get", "post", "put", "delete", "patch", "head", "options"}


def module_name_for(rel_path: str) -> str:
    """'app/routes/invoices.py' -> 'app.routes.invoices'; package __init__ -> package."""
    parts = rel_path[:-3].split("/") if rel_path.endswith(".py") else rel_path.split("/")
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


class PythonAnalyzer:
    """Analyzes all Python files of a repository and resolves local imports."""

    def __init__(self, repo_dir: Path, py_paths: list[str]):
        self.repo_dir = repo_dir
        self.py_paths = py_paths
        # dotted module name -> repo-relative path
        self.module_map: dict[str, str] = {}
        for p in py_paths:
            self.module_map[module_name_for(p)] = p

    # ── import resolution ─────────────────────────────────────────────

    def _resolve_dotted(self, dotted: str) -> str | None:
        """Resolve a dotted module to a local file, trying longest prefix first."""
        if not dotted:
            return None
        parts = dotted.split(".")
        for i in range(len(parts), 0, -1):
            hit = self.module_map.get(".".join(parts[:i]))
            if hit:
                return hit
        return None

    def _package_parts(self, rel_path: str) -> list[str]:
        """Package a file belongs to (for resolving relative imports)."""
        parts = module_name_for(rel_path).split(".")
        if rel_path.endswith("__init__.py"):
            return parts if parts != [""] else []
        return parts[:-1]

    def resolve_import(
        self, rel_path: str, node: ast.Import | ast.ImportFrom
    ) -> list[dict[str, Any]]:
        """Return one record per imported name with local resolution when possible."""
        records: list[dict[str, Any]] = []
        if isinstance(node, ast.Import):
            for alias in node.names:
                records.append(
                    {
                        "module": alias.name,
                        "names": [],
                        "level": 0,
                        "resolved": self._resolve_dotted(alias.name),
                    }
                )
            return records

        # ImportFrom
        base_parts: list[str]
        if node.level and node.level > 0:
            pkg = self._package_parts(rel_path)
            cut = len(pkg) - (node.level - 1)
            base_parts = pkg[:cut] if cut > 0 else []
        else:
            base_parts = []
        module_parts = node.module.split(".") if node.module else []
        full_module = ".".join(base_parts + module_parts)

        names = [a.name for a in node.names]
        # `from pkg import name` may target pkg.name (a submodule) or pkg itself
        resolved = None
        for name in names:
            if name == "*":
                continue
            candidate = self._resolve_dotted(f"{full_module}.{name}" if full_module else name)
            if candidate:
                records.append(
                    {"module": full_module, "names": [name], "level": node.level,
                     "resolved": candidate}
                )
            else:
                resolved = resolved or self._resolve_dotted(full_module)
                records.append(
                    {"module": full_module, "names": [name], "level": node.level,
                     "resolved": resolved}
                )
        return records

    # ── per-file analysis ─────────────────────────────────────────────

    def analyze_file(self, rel_path: str) -> dict[str, Any]:
        result: dict[str, Any] = {
            "path": rel_path,
            "module": module_name_for(rel_path),
            "imports": [],
            "functions": [],
            "classes": [],
            "routes": [],
            "external_libs": [],
            "local_dependencies": [],
            "error": None,
        }
        try:
            source = (self.repo_dir / rel_path).read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source)
        except SyntaxError as exc:
            result["error"] = f"SyntaxError: {exc}"
            return result
        except OSError as exc:
            result["error"] = f"ReadError: {exc}"
            return result

        local_deps: set[str] = set()
        external: set[str] = set()

        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                for rec in self.resolve_import(rel_path, node):
                    result["imports"].append(rec)
                    if rec["resolved"] and rec["resolved"] != rel_path:
                        local_deps.add(rec["resolved"])
                    elif rec["module"]:
                        top = rec["module"].split(".")[0]
                        if top and top not in sys.stdlib_module_names:
                            external.add(top)

        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                result["functions"].append(self._function_info(node))
                result["routes"].extend(self._routes_of(node))
            elif isinstance(node, ast.ClassDef):
                methods = []
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        methods.append(self._function_info(item))
                        result["routes"].extend(self._routes_of(item))
                result["classes"].append(
                    {
                        "name": node.name,
                        "bases": [self._safe_unparse(b) for b in node.bases],
                        "decorators": [self._safe_unparse(d) for d in node.decorator_list],
                        "methods": methods,
                        "lineno": node.lineno,
                    }
                )

        result["local_dependencies"] = sorted(local_deps)
        result["external_libs"] = sorted(external)
        return result

    def analyze_all(self) -> dict[str, dict[str, Any]]:
        return {p: self.analyze_file(p) for p in self.py_paths}

    # ── helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _safe_unparse(node: ast.AST) -> str:
        try:
            return ast.unparse(node)
        except Exception:
            return "<unparseable>"

    def _function_info(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> dict[str, Any]:
        return {
            "name": node.name,
            "args": [a.arg for a in node.args.args],
            "decorators": [self._safe_unparse(d) for d in node.decorator_list],
            "is_async": isinstance(node, ast.AsyncFunctionDef),
            "lineno": node.lineno,
        }

    def _routes_of(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[dict[str, Any]]:
        """Detect Flask/FastAPI style route decorators: @x.route(...), @x.get(...), ..."""
        routes: list[dict[str, Any]] = []
        for dec in node.decorator_list:
            if not (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute)):
                continue
            attr = dec.func.attr
            if attr not in ROUTE_DECORATOR_ATTRS:
                continue
            if not (dec.args and isinstance(dec.args[0], ast.Constant)
                    and isinstance(dec.args[0].value, str)):
                continue
            path = dec.args[0].value
            methods: list[str] = []
            if attr == "route":
                for kw in dec.keywords:
                    if kw.arg == "methods" and isinstance(kw.value, (ast.List, ast.Tuple)):
                        methods = [
                            e.value for e in kw.value.elts
                            if isinstance(e, ast.Constant) and isinstance(e.value, str)
                        ]
                methods = methods or ["GET"]
            else:
                methods = [attr.upper()]
            routes.append(
                {
                    "path": path,
                    "methods": methods,
                    "function": node.name,
                    "decorator": self._safe_unparse(dec),
                    "lineno": node.lineno,
                }
            )
        return routes
