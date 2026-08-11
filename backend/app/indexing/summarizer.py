"""Level-1 (repository) and Level-2 (folder) summaries for tiered LLM context.

The structure is built deterministically from the scan + AST results; an
optional single LLM call (made by the indexing phase) fills in the free-text
`purpose` / folder `responsibility` fields.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from app.indexing.scanner import folder_of

ENTRY_POINT_NAMES = {"run.py", "main.py", "app.py", "wsgi.py", "asgi.py", "manage.py"}


def _read_head(repo_dir: Path, rel: str, max_chars: int = 1500) -> str:
    try:
        return (repo_dir / rel).read_text(encoding="utf-8", errors="replace")[:max_chars]
    except OSError:
        return ""


def build_index_document(
    run_id: str,
    repository_url: str,
    repo_dir: Path,
    files: list[dict[str, Any]],
    analyses: dict[str, dict[str, Any]],
    tree: str,
) -> dict[str, Any]:
    by_language: dict[str, int] = {}
    by_category: dict[str, int] = {}
    for f in files:
        if f["language"]:
            by_language[f["language"]] = by_language.get(f["language"], 0) + 1
        by_category[f["category"]] = by_category.get(f["category"], 0) + 1

    dependency_files = [f["path"] for f in files if f["category"] == "dependency"]
    technologies: list[str] = []
    for dep_file in dependency_files:
        head = _read_head(repo_dir, dep_file, 2000)
        for line in head.splitlines():
            line = line.split("#")[0].strip()
            if line and not line.startswith(("[", "{", '"', "-e ")):
                pkg = (
                    line.split("==")[0].split(">=")[0].split("<=")[0]
                    .split("~=")[0].split(";")[0].strip()
                )
                if pkg and len(pkg) < 40 and pkg not in technologies:
                    technologies.append(pkg)

    readme = next((f["path"] for f in files if f["path"].lower().startswith("readme")), None)

    # folder summaries (Level 2)
    folder_summaries: dict[str, dict[str, Any]] = {}
    for f in files:
        if f["category"] not in ("source", "test"):
            continue
        folder = folder_of(f["path"])
        entry = folder_summaries.setdefault(
            folder, {"folder": folder, "files": [], "responsibility": ""}
        )
        info = analyses.get(f["path"], {})
        entry["files"].append(
            {
                "path": f["path"],
                "language": f["language"],
                "category": f["category"],
                "lines": f["lines"],
                "functions": [fn["name"] for fn in info.get("functions", [])],
                "classes": [c["name"] for c in info.get("classes", [])],
                "routes": [
                    f"{'|'.join(r['methods'])} {r['path']}" for r in info.get("routes", [])
                ],
            }
        )

    entry_points = sorted(
        f["path"] for f in files
        if f["path"].split("/")[-1] in ENTRY_POINT_NAMES and f["category"] == "source"
    )

    return {
        "run_id": run_id,
        "repository": repository_url,
        "source_language": max(by_language, key=by_language.get) if by_language else None,
        "status": "completed",
        "tree": tree,
        "stats": {
            "total_files": len(files),
            "by_language": by_language,
            "by_category": by_category,
        },
        "files": [f["path"] for f in files],
        "folders": sorted(folder_summaries.keys()),
        "dependency_files": dependency_files,
        "technologies": technologies[:30],
        "entry_points": entry_points,
        "readme_head": _read_head(repo_dir, readme) if readme else "",
        "purpose": "",  # filled by LLM enrichment when available
        "folder_summaries": folder_summaries,
    }


# ── prompt renderers ─────────────────────────────────────────────────


def render_repo_summary(index: dict[str, Any]) -> str:
    """Level-1 context: compact repository overview for system prompts."""
    stats = index.get("stats", {})
    lines = [
        f"Repository: {index.get('repository', '?')}",
        f"Primary language: {index.get('source_language') or 'unknown'}",
        f"Files: {stats.get('total_files', 0)} "
        f"(by category: {stats.get('by_category', {})})",
        f"Technologies/dependencies: {', '.join(index.get('technologies', [])) or 'unknown'}",
        f"Entry points: {', '.join(index.get('entry_points', [])) or 'none detected'}",
        f"Dependency files: {', '.join(index.get('dependency_files', [])) or 'none'}",
        f"Folders: {', '.join(index.get('folders', []))}",
    ]
    if index.get("purpose"):
        lines.append(f"Purpose: {index['purpose']}")
    if index.get("tree"):
        lines.append("\nRepository tree:\n" + index["tree"])
    return "\n".join(lines)


def render_folder_summary(index: dict[str, Any], folder: str) -> str:
    """Level-2 context: one folder's files and symbols."""
    fs = index.get("folder_summaries", {}).get(folder)
    if not fs:
        return f"No summary available for folder '{folder}'."
    lines = [f"Folder: {folder}/"]
    if fs.get("responsibility"):
        lines.append(f"Responsibility: {fs['responsibility']}")
    lines.append("Files:")
    for f in fs["files"]:
        detail_parts = []
        if f["classes"]:
            detail_parts.append(f"classes: {', '.join(f['classes'])}")
        if f["functions"]:
            detail_parts.append(f"functions: {', '.join(f['functions'][:15])}")
        if f["routes"]:
            detail_parts.append(f"routes: {', '.join(f['routes'])}")
        detail = f" — {'; '.join(detail_parts)}" if detail_parts else ""
        lines.append(f"- {f['path']} ({f['lines']} lines){detail}")
    return "\n".join(lines)
