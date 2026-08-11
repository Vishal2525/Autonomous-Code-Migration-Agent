import pytest

from app.models.enums import RunMode
from app.tools.file_tools import (
    CreateFileArgs,
    DeleteFileArgs,
    EditFileArgs,
    ReadFileArgs,
    ReplaceLinesArgs,
    WriteFileArgs,
    create_file,
    delete_file,
    edit_file,
    read_file,
    replace_lines,
    resolve_path,
    write_file,
)
from app.tools.registry import ApprovalRequiredError, ToolError


async def test_read_file(repo_ctx):
    result = await read_file(repo_ctx, ReadFileArgs(path="app/sample.py"))
    assert 'GREETING = "hello"' in result["content"]
    assert result["total_lines"] >= 4


async def test_read_file_line_range(repo_ctx):
    result = await read_file(repo_ctx, ReadFileArgs(path="notes.txt", start_line=2, end_line=2))
    assert result["content"] == "second\n"


async def test_read_missing_file(repo_ctx):
    with pytest.raises(ToolError):
        await read_file(repo_ctx, ReadFileArgs(path="nope.py"))


def test_sandbox_rejects_escape(repo_ctx):
    for bad in ["../outside.txt", "..\\outside.txt", "/etc/passwd", "C:\\Windows\\x"]:
        with pytest.raises(ToolError):
            resolve_path(repo_ctx, bad)


def test_sandbox_rejects_git_dir(repo_ctx):
    (repo_ctx.repo_dir / ".git").mkdir()
    with pytest.raises(ToolError):
        resolve_path(repo_ctx, ".git/config")


async def test_edit_file_replaces_exact_string(repo_ctx):
    await edit_file(
        repo_ctx,
        EditFileArgs(path="app/sample.py", old_string='GREETING = "hello"',
                     new_string='GREETING = "hi"'),
    )
    content = (repo_ctx.repo_dir / "app/sample.py").read_text()
    assert 'GREETING = "hi"' in content
    assert "app/sample.py" in repo_ctx.touched_files


async def test_edit_file_not_found_string(repo_ctx):
    with pytest.raises(ToolError, match="not found"):
        await edit_file(
            repo_ctx,
            EditFileArgs(path="app/sample.py", old_string="does-not-exist", new_string="x"),
        )


async def test_edit_file_ambiguous_string(repo_ctx):
    (repo_ctx.repo_dir / "dup.py").write_text("x = 1\nx = 1\n", encoding="utf-8")
    with pytest.raises(ToolError, match="occurs 2 times"):
        await edit_file(repo_ctx, EditFileArgs(path="dup.py", old_string="x = 1", new_string="x = 2"))
    # replace_all resolves the ambiguity
    result = await edit_file(
        repo_ctx,
        EditFileArgs(path="dup.py", old_string="x = 1", new_string="x = 2", replace_all=True),
    )
    assert result["replacements"] == 2


async def test_syntax_gate_blocks_broken_python(repo_ctx):
    before = (repo_ctx.repo_dir / "app/sample.py").read_text()
    with pytest.raises(ToolError, match="not valid Python"):
        await edit_file(
            repo_ctx,
            EditFileArgs(path="app/sample.py", old_string="def greet(name):",
                         new_string="def greet(name:"),
        )
    assert (repo_ctx.repo_dir / "app/sample.py").read_text() == before  # unchanged


async def test_write_requires_existing_and_create_requires_new(repo_ctx):
    with pytest.raises(ToolError):
        await write_file(repo_ctx, WriteFileArgs(path="new.py", content="x = 1\n"))
    await create_file(repo_ctx, CreateFileArgs(path="new.py", content="x = 1\n"))
    with pytest.raises(ToolError):
        await create_file(repo_ctx, CreateFileArgs(path="new.py", content="x = 2\n"))
    await write_file(repo_ctx, WriteFileArgs(path="new.py", content="x = 3\n"))
    assert (repo_ctx.repo_dir / "new.py").read_text() == "x = 3\n"


async def test_replace_lines(repo_ctx):
    await replace_lines(
        repo_ctx,
        ReplaceLinesArgs(path="notes.txt", start_line=2, end_line=3, new_content="middle"),
    )
    assert (repo_ctx.repo_dir / "notes.txt").read_text() == "first\nmiddle\n"


async def test_delete_requires_approval_in_hitl(repo_ctx):
    repo_ctx.mode = RunMode.HITL
    with pytest.raises(ApprovalRequiredError) as exc:
        await delete_file(repo_ctx, DeleteFileArgs(path="notes.txt", reason="cleanup"))
    assert "notes.txt" in exc.value.key
    # once the key is approved, deletion proceeds
    repo_ctx.approved_keys.add(exc.value.key)
    result = await delete_file(repo_ctx, DeleteFileArgs(path="notes.txt", reason="cleanup"))
    assert result["deleted"] is True


async def test_delete_direct_in_auto_mode(repo_ctx):
    result = await delete_file(repo_ctx, DeleteFileArgs(path="notes.txt"))
    assert result["deleted"] is True
    assert not (repo_ctx.repo_dir / "notes.txt").exists()
