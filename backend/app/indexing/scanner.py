"""Repository scan: classify every file and build an ASCII tree."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from app.indexing.cloner import IGNORED_DIRS

LANGUAGE_BY_EXT = {
    ".py": "python", ".js": "javascript", ".jsx": "javascript",
    ".ts": "typescript", ".tsx": "typescript", ".java": "java",
    ".go": "go", ".rb": "ruby", ".rs": "rust", ".php": "php",
    ".cs": "csharp", ".html": "html", ".css": "css", ".sql": "sql",
    ".sh": "shell", ".ps1": "powershell",
}

DEPENDENCY_FILES = {
    "requirements.txt", "requirements-dev.txt", "pyproject.toml", "setup.py",
    "setup.cfg", "pipfile", "pipfile.lock", "poetry.lock", "package.json",
    "package-lock.json", "yarn.lock", "pom.xml", "build.gradle", "go.mod",
}

CONFIG_EXTS = {".toml", ".cfg", ".ini", ".yaml", ".yml", ".json", ".env"}
DOC_EXTS = {".md", ".rst"}

MAX_FILE_BYTES = 2_000_000  # skip content stats above this


def classify_file(rel_path: Path) -> dict[str, Any]:
    name = rel_path.name.lower()
    ext = rel_path.suffix.lower()
    parts = [p.lower() for p in rel_path.parts]

    language = LANGUAGE_BY_EXT.get(ext)
    if name in DEPENDENCY_FILES:
        category = "dependency"
    elif "test" in parts or "tests" in parts or name.startswith("test_") or name.endswith("_test.py"):
        category = "test" if language else "other"
    elif ext in DOC_EXTS or name == "readme.txt":
        category = "docs"
    elif language in (None,) and ext in CONFIG_EXTS:
        category = "config"
    elif language:
        category = "source"
    elif ext in CONFIG_EXTS:
        category = "config"
    else:
        category = "other"
    return {"language": language, "category": category}


def scan_repository(repo_dir: Path) -> list[dict[str, Any]]:
    """Walk the working copy and return one record per file."""
    records: list[dict[str, Any]] = []
    for path in sorted(repo_dir.rglob("*")):
        if path.is_dir():
            continue
        rel = path.relative_to(repo_dir)
        if any(part in IGNORED_DIRS for part in rel.parts):
            continue
        try:
            size = path.stat().st_size
        except OSError:
            continue
        lines = 0
        if size <= MAX_FILE_BYTES:
            try:
                lines = path.read_text(encoding="utf-8", errors="replace").count("\n") + 1
            except OSError:
                lines = 0
        info = classify_file(rel)
        records.append(
            {
                "path": rel.as_posix(),
                "size": size,
                "lines": lines,
                "language": info["language"],
                "category": info["category"],
            }
        )
    return records


def build_tree(files: list[dict[str, Any]], max_entries: int = 400) -> str:
    """Render an ASCII tree of the scanned files (bounded for prompts)."""
    tree: dict[str, Any] = {}
    for f in files[:max_entries]:
        node = tree
        parts = f["path"].split("/")
        for part in parts[:-1]:
            node = node.setdefault(part + "/", {})
        node[parts[-1]] = None

    lines: list[str] = []

    def render(node: dict[str, Any], prefix: str) -> None:
        entries = sorted(node.items(), key=lambda kv: (kv[1] is None, kv[0]))
        for i, (name, child) in enumerate(entries):
            connector = "└── " if i == len(entries) - 1 else "├── "
            lines.append(prefix + connector + name)
            if isinstance(child, dict):
                extension = "    " if i == len(entries) - 1 else "│   "
                render(child, prefix + extension)

    render(tree, "")
    if len(files) > max_entries:
        lines.append(f"... ({len(files) - max_entries} more files)")
    return "\n".join(lines)


def folder_of(path: str) -> str:
    return path.rsplit("/", 1)[0] if "/" in path else "."
