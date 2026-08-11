"""Git snapshot system for the run's working copy.

Every completed task becomes a commit; failed modifications roll back to the
pre-task SHA (including untracked files the attempt created).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from git import Repo
from git.exc import GitCommandError

from app.logging_config import get_logger

log = get_logger("gitops")


class GitError(Exception):
    pass


class GitManager:
    def __init__(self, repo_dir: Path):
        self.repo_dir = Path(repo_dir)
        if not self.repo_dir.is_dir():
            raise GitError(f"Repository directory not found: {self.repo_dir}")
        self._repo: Repo | None = None

    @property
    def repo(self) -> Repo:
        if self._repo is None:
            self._repo = Repo(self.repo_dir)
        return self._repo

    # ── setup ─────────────────────────────────────────────────────────

    def ensure_repo(self, run_id: str) -> str:
        """Init (if needed), set identity, create the migration branch.

        Returns the baseline SHA all migration work builds on.
        """
        if not (self.repo_dir / ".git").exists():
            self._repo = Repo.init(self.repo_dir)
        self._configure_identity()
        self._configure_excludes()

        if not self.repo.head.is_valid() or self.repo.is_dirty(untracked_files=True):
            self.repo.git.add("-A")
            if self.repo.is_dirty(untracked_files=True) or not self.repo.head.is_valid():
                self.repo.index.commit("Baseline import")

        branch = f"migration-{run_id[:8]}"
        if branch not in [h.name for h in self.repo.heads]:
            self.repo.git.checkout("-b", branch)
        else:
            self.repo.git.checkout(branch)
        sha = self.current_sha()
        log.info("git_ready", branch=branch, baseline=sha[:10])
        return sha

    def _configure_identity(self) -> None:
        with self.repo.config_writer() as cw:
            cw.set_value("user", "name", "Migration Agent")
            cw.set_value("user", "email", "agent@migration.local")
            # OneDrive/Windows friendliness
            cw.set_value("core", "autocrlf", "false")

    def _configure_excludes(self) -> None:
        """Repo-local ignores (.git/info/exclude) so test-run artifacts never
        pollute snapshots or dirty-tree checks — without editing the repo's files."""
        exclude = self.repo_dir / ".git" / "info" / "exclude"
        wanted = ["__pycache__/", "*.pyc", ".pytest_cache/", ".venv/", "venv/", "*.egg-info/"]
        try:
            existing = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
            missing = [w for w in wanted if w not in existing]
            if missing:
                exclude.parent.mkdir(parents=True, exist_ok=True)
                exclude.write_text(
                    existing.rstrip("\n") + "\n" + "\n".join(missing) + "\n",
                    encoding="utf-8",
                )
        except OSError:
            pass

    # ── snapshots & rollback ──────────────────────────────────────────

    def current_sha(self) -> str:
        return self.repo.head.commit.hexsha

    def is_dirty(self) -> bool:
        return self.repo.is_dirty(untracked_files=True)

    def snapshot(self, message: str) -> dict[str, Any]:
        """Stage everything and commit. No-op (same SHA) when nothing changed."""
        self.repo.git.add("-A")
        if not self.repo.is_dirty(untracked_files=True):
            return {"sha": self.current_sha(), "committed": False}
        commit = self.repo.index.commit(message)
        log.info("git_snapshot", sha=commit.hexsha[:10], message=message[:80])
        return {"sha": commit.hexsha, "committed": True}

    def rollback(self, sha: str) -> str:
        """Hard reset to `sha` and drop untracked files created since."""
        try:
            self.repo.git.reset("--hard", sha)
            self.repo.git.clean("-fd")
        except GitCommandError as exc:
            raise GitError(f"Rollback to {sha[:10]} failed: {exc}") from exc
        log.info("git_rollback", sha=sha[:10])
        return self.current_sha()

    # ── inspection ────────────────────────────────────────────────────

    def status(self) -> str:
        return self.repo.git.status("--porcelain")

    def diff_patch(
        self, base: str, head: str = "HEAD", path: str | None = None, max_chars: int = 60000
    ) -> str:
        args = [f"{base}..{head}"]
        if path:
            args += ["--", path]
        try:
            patch = self.repo.git.diff(*args)
        except GitCommandError as exc:
            raise GitError(f"git diff failed: {exc}") from exc
        if len(patch) > max_chars:
            patch = patch[:max_chars] + f"\n... (diff truncated at {max_chars} chars)"
        return patch

    def working_diff(self, max_chars: int = 40000) -> str:
        patch = self.repo.git.diff("HEAD")
        return patch[:max_chars]

    def diff_names(self, base: str, head: str = "HEAD") -> list[dict[str, str]]:
        """[{status: added|modified|deleted|renamed, path}] between two commits."""
        try:
            raw = self.repo.git.diff(f"{base}..{head}", "--name-status")
        except GitCommandError as exc:
            raise GitError(f"git diff failed: {exc}") from exc
        mapping = {"A": "added", "M": "modified", "D": "deleted"}
        out: list[dict[str, str]] = []
        for line in raw.splitlines():
            parts = line.split("\t")
            if len(parts) < 2:
                continue
            code = parts[0][0]
            if code == "R" and len(parts) >= 3:
                out.append({"status": "renamed", "path": parts[2], "old_path": parts[1]})
            else:
                out.append({"status": mapping.get(code, code), "path": parts[-1]})
        return out

    def commits_since(self, base: str) -> int:
        try:
            return int(self.repo.git.rev_list("--count", f"{base}..HEAD"))
        except GitCommandError:
            return 0

    def log_entries(self, n: int = 20) -> list[dict[str, str]]:
        entries = []
        for commit in self.repo.iter_commits(max_count=n):
            entries.append(
                {
                    "sha": commit.hexsha,
                    "message": commit.message.strip().splitlines()[0] if commit.message else "",
                    "date": commit.committed_datetime.isoformat(),
                }
            )
        return entries

    def has_commit(self, sha: str) -> bool:
        try:
            self.repo.commit(sha)
            return True
        except Exception:
            return False
