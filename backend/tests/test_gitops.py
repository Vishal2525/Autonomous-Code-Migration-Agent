from pathlib import Path

from app.gitops.manager import GitManager


def _make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "main.py").write_text("print('v1')\n", encoding="utf-8")
    return repo


def test_ensure_repo_creates_baseline_and_branch(tmp_path):
    repo = _make_repo(tmp_path)
    git = GitManager(repo)
    baseline = git.ensure_repo("abcdef123456")
    assert len(baseline) == 40
    assert git.repo.active_branch.name == "migration-abcdef12"
    assert not git.is_dirty()


def test_snapshot_and_rollback_roundtrip(tmp_path):
    repo = _make_repo(tmp_path)
    git = GitManager(repo)
    baseline = git.ensure_repo("run12345")

    (repo / "main.py").write_text("print('v2')\n", encoding="utf-8")
    snap = git.snapshot("TASK-001: change main")
    assert snap["committed"] is True
    sha_v2 = snap["sha"]
    assert sha_v2 != baseline

    # further changes incl. a brand-new untracked file
    (repo / "main.py").write_text("print('v3')\n", encoding="utf-8")
    (repo / "junk.py").write_text("broken(\n", encoding="utf-8")
    git.rollback(sha_v2)
    assert (repo / "main.py").read_text() == "print('v2')\n"
    assert not (repo / "junk.py").exists()  # untracked files cleaned

    git.rollback(baseline)
    assert (repo / "main.py").read_text() == "print('v1')\n"


def test_snapshot_without_changes_is_noop(tmp_path):
    repo = _make_repo(tmp_path)
    git = GitManager(repo)
    git.ensure_repo("run12345")
    first = git.snapshot("no changes")
    assert first["committed"] is False


def test_diff_names_and_commit_count(tmp_path):
    repo = _make_repo(tmp_path)
    git = GitManager(repo)
    baseline = git.ensure_repo("run12345")
    (repo / "main.py").write_text("print('v2')\n", encoding="utf-8")
    (repo / "extra.py").write_text("x = 1\n", encoding="utf-8")
    git.snapshot("TASK-001")
    changes = {c["path"]: c["status"] for c in git.diff_names(baseline)}
    assert changes == {"main.py": "modified", "extra.py": "added"}
    assert git.commits_since(baseline) == 1
