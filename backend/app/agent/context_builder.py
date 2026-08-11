"""Tiered context assembly (Level 1 always, Level 2 selectively, Level 3 via tools).

The full repository is NEVER put into the LLM context. Prompts get the compact
L1 summary plus targeted L2 folder summaries; the agent pulls L3 file content
itself through read_file when it decides it needs it.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from app.indexing.summarizer import render_folder_summary, render_repo_summary


def level1(index: dict[str, Any]) -> str:
    return render_repo_summary(index)


def level2_all(index: dict[str, Any], max_chars: int = 12000) -> str:
    """All folder summaries, bounded — used by the planner."""
    chunks = []
    for folder in index.get("folders", []):
        chunks.append(render_folder_summary(index, folder))
    text = "\n\n".join(chunks)
    if len(text) > max_chars:
        text = text[:max_chars] + "\n... (folder summaries truncated)"
    return text


def dependency_file_contents(index: dict[str, Any], repo_dir: Path, max_chars: int = 4000) -> str:
    chunks = []
    for rel in index.get("dependency_files", []):
        try:
            content = (repo_dir / rel).read_text(encoding="utf-8", errors="replace")[:2000]
        except OSError:
            continue
        chunks.append(f"--- {rel} ---\n{content}")
    return "\n".join(chunks)[:max_chars]


def dependency_graph_digest(deps: list[dict[str, Any]], max_lines: int = 120) -> str:
    """Compact 'A -> [B, C]' lines for the planner."""
    lines = []
    for d in deps:
        if d.get("dependencies"):
            lines.append(f"{d['source_file']} -> {', '.join(d['dependencies'])}")
    lines = lines[:max_lines]
    return "\n".join(lines) if lines else "(no local imports detected)"
