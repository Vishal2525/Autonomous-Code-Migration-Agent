"""Dependency graph (forward + reverse) built from AST analysis results."""
from __future__ import annotations

from typing import Any


def build_dependency_graph(
    analyses: dict[str, dict[str, Any]],
) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """Return (dependencies, reverse_dependencies) keyed by repo-relative path."""
    deps: dict[str, list[str]] = {}
    reverse: dict[str, list[str]] = {path: [] for path in analyses}

    for path, info in analyses.items():
        targets = sorted(set(info.get("local_dependencies", [])) - {path})
        deps[path] = targets
        for target in targets:
            reverse.setdefault(target, [])
            if path not in reverse[target]:
                reverse[target].append(path)

    for target in reverse:
        reverse[target].sort()
    return deps, reverse


def dependency_docs(
    deps: dict[str, list[str]], reverse: dict[str, list[str]]
) -> list[dict[str, Any]]:
    """Flatten graphs into MongoDB `dependencies` documents."""
    docs = []
    for source, targets in deps.items():
        docs.append(
            {
                "source_file": source,
                "dependencies": targets,
                "reverse_dependencies": reverse.get(source, []),
            }
        )
    return docs


def execution_order(deps: dict[str, list[str]], files: list[str]) -> list[str]:
    """Topological-ish order: dependencies before dependents (cycles broken by name)."""
    remaining = set(files)
    ordered: list[str] = []
    while remaining:
        ready = sorted(
            f for f in remaining
            if not (set(deps.get(f, [])) & remaining - {f})
        )
        if not ready:  # cycle — break it deterministically
            ready = [sorted(remaining)[0]]
        for f in ready:
            ordered.append(f)
            remaining.discard(f)
    return ordered
