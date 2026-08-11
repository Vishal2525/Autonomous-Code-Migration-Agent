"""Clone the target repository into the run workspace.

Supports:
- https://... / git@... remotes  → real ``git clone``
- local directory paths (or file:// URLs) → filtered copy + fresh ``git init``
  (useful for offline demos; the original repository is never modified)
"""
from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

from app.config import settings
from app.logging_config import get_logger

log = get_logger("indexing.cloner")

#: directory names never copied / scanned
IGNORED_DIRS = {
    ".git", "node_modules", "venv", ".venv", "env", "__pycache__",
    "dist", "build", "target", "coverage", ".idea", ".vscode",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", ".tox", ".eggs",
}


class CloneError(Exception):
    pass


def _is_remote(url: str) -> bool:
    return url.startswith(("http://", "https://", "git@", "ssh://"))


async def clone_repository(repository_url: str, dest: Path) -> None:
    """Materialize the repository at ``dest`` (which must not already exist)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        raise CloneError(f"Destination already exists: {dest}")

    if _is_remote(repository_url):
        await _git_clone(repository_url, dest)
    else:
        src = Path(repository_url.removeprefix("file://").removeprefix("file:"))
        if not src.is_dir():
            raise CloneError(f"Local repository path not found: {src}")
        await asyncio.to_thread(_copy_tree, src, dest)
    log.info("repository_cloned", url=repository_url, dest=str(dest))


async def _git_clone(url: str, dest: Path) -> None:
    proc = await asyncio.create_subprocess_exec(
        "git", "clone", "--depth", "1", url, str(dest),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=settings.clone_timeout
        )
    except asyncio.TimeoutError:
        proc.kill()
        raise CloneError(f"git clone timed out after {settings.clone_timeout}s")
    if proc.returncode != 0:
        raise CloneError(
            f"git clone failed (exit {proc.returncode}): "
            f"{stderr.decode(errors='replace')[-2000:]}"
        )


def _copy_tree(src: Path, dest: Path) -> None:
    shutil.copytree(
        src,
        dest,
        ignore=shutil.ignore_patterns(*IGNORED_DIRS),
        dirs_exist_ok=False,
    )
