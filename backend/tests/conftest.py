import pytest

from app.models.enums import Phase, RunMode
from app.tools.registry import ToolContext


async def _noop_emit(*args, **kwargs):
    pass


@pytest.fixture()
def repo_ctx(tmp_path):
    """ToolContext over a small temp repository (no DB / git / LLM needed)."""
    repo = tmp_path / "repository"
    repo.mkdir()
    (repo / "app").mkdir()
    (repo / "app" / "sample.py").write_text(
        'GREETING = "hello"\n\n\ndef greet(name):\n    return f"{GREETING} {name}"\n',
        encoding="utf-8",
    )
    (repo / "notes.txt").write_text("first\nsecond\nthird\n", encoding="utf-8")
    return ToolContext(
        run_id="test-run",
        repo_dir=repo,
        workspace_dir=tmp_path,
        mode=RunMode.AUTO,
        phase=Phase.EXECUTION,
        store=None,
        git=None,
        emit=_noop_emit,
    )
