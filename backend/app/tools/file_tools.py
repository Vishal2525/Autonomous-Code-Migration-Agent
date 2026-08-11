"""File tools — sandboxed to the run's repository directory.

Editing strategy (per spec): targeted string replacement first, line-range
edits second, full rewrite only when necessary. Python files are syntax-checked
with ast.parse BEFORE anything is written to disk.
"""
from __future__ import annotations

import ast
from pathlib import Path

from pydantic import BaseModel, Field

from app.indexing.cloner import IGNORED_DIRS
from app.models.enums import ApprovalGate, EventType, RunMode
from app.tools.registry import (
    ApprovalRequiredError,
    Tool,
    ToolContext,
    ToolError,
    ToolRegistry,
)

MAX_READ_BYTES = 400_000
DEPENDENCY_FILE_NAMES = {
    "requirements.txt", "requirements-dev.txt", "pyproject.toml", "setup.py",
    "setup.cfg", "pipfile", "package.json",
}


def resolve_path(ctx: ToolContext, rel_path: str) -> Path:
    """Resolve a repo-relative path; reject escapes, absolute paths, and .git."""
    if not rel_path or rel_path.strip() == "":
        raise ToolError("Path must not be empty")
    candidate = Path(rel_path)
    if candidate.is_absolute() or rel_path.startswith(("/", "\\")):
        raise ToolError(f"Absolute paths are not allowed: {rel_path}")
    resolved = (ctx.repo_dir / candidate).resolve()
    root = ctx.repo_dir.resolve()
    if not resolved.is_relative_to(root):
        raise ToolError(f"Path escapes the repository sandbox: {rel_path}")
    rel_parts = resolved.relative_to(root).parts
    if rel_parts and rel_parts[0] == ".git":
        raise ToolError("The .git directory cannot be accessed by tools")
    return resolved


def _rel(ctx: ToolContext, path: Path) -> str:
    return path.resolve().relative_to(ctx.repo_dir.resolve()).as_posix()


def validate_python_syntax(rel_path: str, content: str) -> None:
    if rel_path.endswith(".py"):
        try:
            ast.parse(content)
        except SyntaxError as exc:
            raise ToolError(
                f"Rejected: the new content of {rel_path} is not valid Python "
                f"(line {exc.lineno}: {exc.msg}). The file was NOT modified."
            )


def _guard_dependency_file(ctx: ToolContext, rel_path: str) -> None:
    """Dependency-config changes need approval in HITL mode."""
    if ctx.mode != RunMode.HITL:
        return
    if Path(rel_path).name.lower() not in DEPENDENCY_FILE_NAMES:
        return
    key = f"DEPENDENCY:{rel_path}"
    if key in ctx.approved_keys:
        return
    raise ApprovalRequiredError(
        gate=ApprovalGate.DEPENDENCY_CHANGE,
        key=key,
        detail=f"The agent wants to modify the dependency file '{rel_path}'.",
        data={"file": rel_path},
    )


# ── schemas ──────────────────────────────────────────────────────────


class ReadFileArgs(BaseModel):
    path: str = Field(description="Repository-relative file path")
    start_line: int | None = Field(default=None, ge=1, description="1-indexed start line")
    end_line: int | None = Field(default=None, ge=1, description="1-indexed end line (inclusive)")


class WriteFileArgs(BaseModel):
    path: str = Field(description="Repository-relative path of an EXISTING file")
    content: str = Field(description="Complete new file content")


class CreateFileArgs(BaseModel):
    path: str = Field(description="Repository-relative path of a NEW file")
    content: str


class EditFileArgs(BaseModel):
    path: str
    old_string: str = Field(min_length=1, description="Exact text to replace")
    new_string: str = Field(description="Replacement text")
    replace_all: bool = Field(default=False, description="Replace every occurrence")


class ReplaceLinesArgs(BaseModel):
    path: str
    start_line: int = Field(ge=1, description="1-indexed first line to replace")
    end_line: int = Field(ge=1, description="1-indexed last line to replace (inclusive)")
    new_content: str = Field(description="Text replacing the given line range")


class DeleteFileArgs(BaseModel):
    path: str
    reason: str = Field(default="", description="Why this file should be deleted")


class ListFilesArgs(BaseModel):
    folder: str | None = Field(default=None, description="Limit to this folder")
    suffix: str | None = Field(default=None, description="e.g. '.py'")


# ── handlers ─────────────────────────────────────────────────────────


async def read_file(ctx: ToolContext, args: ReadFileArgs):
    path = resolve_path(ctx, args.path)
    if not path.is_file():
        raise ToolError(f"File not found: {args.path}")
    if path.stat().st_size > MAX_READ_BYTES:
        raise ToolError(
            f"File too large ({path.stat().st_size} bytes); read it in slices "
            "using start_line/end_line."
        )
    content = path.read_text(encoding="utf-8", errors="replace")
    lines = content.splitlines(keepends=True)
    total = len(lines)
    if args.start_line or args.end_line:
        start = (args.start_line or 1) - 1
        end = args.end_line or total
        content = "".join(lines[start:end])
    return {"path": args.path, "total_lines": total, "content": content}


async def write_file(ctx: ToolContext, args: WriteFileArgs):
    path = resolve_path(ctx, args.path)
    rel = _rel(ctx, path)
    if not path.is_file():
        raise ToolError(f"File does not exist: {rel}. Use create_file for new files.")
    _guard_dependency_file(ctx, rel)
    validate_python_syntax(rel, args.content)
    path.write_text(args.content, encoding="utf-8", newline="\n")
    ctx.touched_files.add(rel)
    await ctx.emit(EventType.FILE_MODIFIED, f"Rewrote {rel}", {"file": rel})
    return {"path": rel, "written_chars": len(args.content)}


async def create_file(ctx: ToolContext, args: CreateFileArgs):
    path = resolve_path(ctx, args.path)
    rel = _rel(ctx, path)
    if path.exists():
        raise ToolError(f"File already exists: {rel}. Use edit_file or write_file.")
    _guard_dependency_file(ctx, rel)
    validate_python_syntax(rel, args.content)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(args.content, encoding="utf-8", newline="\n")
    ctx.touched_files.add(rel)
    await ctx.emit(EventType.FILE_CREATED, f"Created {rel}", {"file": rel})
    return {"path": rel, "written_chars": len(args.content)}


async def edit_file(ctx: ToolContext, args: EditFileArgs):
    path = resolve_path(ctx, args.path)
    rel = _rel(ctx, path)
    if not path.is_file():
        raise ToolError(f"File not found: {rel}")
    _guard_dependency_file(ctx, rel)
    content = path.read_text(encoding="utf-8", errors="replace")
    count = content.count(args.old_string)
    if count == 0:
        raise ToolError(
            f"old_string not found in {rel}. Read the file again and copy the "
            "exact text (whitespace matters)."
        )
    if count > 1 and not args.replace_all:
        raise ToolError(
            f"old_string occurs {count} times in {rel}. Provide more surrounding "
            "context to make it unique, or set replace_all=true."
        )
    new_content = content.replace(args.old_string, args.new_string)
    validate_python_syntax(rel, new_content)
    path.write_text(new_content, encoding="utf-8", newline="\n")
    ctx.touched_files.add(rel)
    await ctx.emit(EventType.FILE_MODIFIED, f"Edited {rel}", {"file": rel})
    return {"path": rel, "replacements": count if args.replace_all else 1}


async def replace_lines(ctx: ToolContext, args: ReplaceLinesArgs):
    path = resolve_path(ctx, args.path)
    rel = _rel(ctx, path)
    if not path.is_file():
        raise ToolError(f"File not found: {rel}")
    _guard_dependency_file(ctx, rel)
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
    if args.start_line > len(lines) or args.end_line > len(lines):
        raise ToolError(f"{rel} has only {len(lines)} lines")
    if args.end_line < args.start_line:
        raise ToolError("end_line must be >= start_line")
    replacement = args.new_content
    if replacement and not replacement.endswith("\n"):
        replacement += "\n"
    new_lines = lines[: args.start_line - 1] + [replacement] + lines[args.end_line:]
    new_content = "".join(new_lines)
    validate_python_syntax(rel, new_content)
    path.write_text(new_content, encoding="utf-8", newline="\n")
    ctx.touched_files.add(rel)
    await ctx.emit(EventType.FILE_MODIFIED, f"Edited {rel} (lines {args.start_line}-{args.end_line})", {"file": rel})
    return {"path": rel, "replaced_lines": args.end_line - args.start_line + 1}


async def delete_file(ctx: ToolContext, args: DeleteFileArgs):
    path = resolve_path(ctx, args.path)
    rel = _rel(ctx, path)
    if not path.is_file():
        raise ToolError(f"File not found: {rel}")
    if ctx.mode == RunMode.HITL:
        key = f"DESTRUCTIVE:{rel}"
        if key not in ctx.approved_keys:
            raise ApprovalRequiredError(
                gate=ApprovalGate.DESTRUCTIVE_CHANGE,
                key=key,
                detail=f"The agent wants to DELETE '{rel}'. Reason: {args.reason or 'not given'}",
                data={"file": rel, "reason": args.reason},
            )
    path.unlink()
    ctx.touched_files.add(rel)
    await ctx.emit(EventType.FILE_DELETED, f"Deleted {rel}", {"file": rel})
    return {"path": rel, "deleted": True}


async def list_files(ctx: ToolContext, args: ListFilesArgs):
    base = resolve_path(ctx, args.folder) if args.folder else ctx.repo_dir
    if not base.is_dir():
        raise ToolError(f"Folder not found: {args.folder}")
    out = []
    for p in sorted(base.rglob("*")):
        if not p.is_file():
            continue
        rel_parts = p.relative_to(ctx.repo_dir).parts
        if any(part in IGNORED_DIRS for part in rel_parts):
            continue
        rel = p.relative_to(ctx.repo_dir).as_posix()
        if args.suffix and not rel.endswith(args.suffix):
            continue
        out.append(rel)
        if len(out) >= 500:
            break
    return {"files": out, "count": len(out)}


def register_file_tools(registry: ToolRegistry) -> None:
    registry.register(Tool(
        name="read_file",
        description="Read a file from the repository (optionally a line range). "
                    "Returns the exact current content — always read before editing.",
        input_model=ReadFileArgs, handler=read_file,
    ))
    registry.register(Tool(
        name="edit_file",
        description="Preferred edit tool: replace an exact string in a file with new text. "
                    "old_string must match the current file content exactly.",
        input_model=EditFileArgs, handler=edit_file, mutating=True,
    ))
    registry.register(Tool(
        name="replace_lines",
        description="Replace an inclusive 1-indexed line range with new content.",
        input_model=ReplaceLinesArgs, handler=replace_lines, mutating=True,
    ))
    registry.register(Tool(
        name="write_file",
        description="Rewrite an existing file completely. Use ONLY when targeted edits "
                    "are impractical (e.g. the whole file changes).",
        input_model=WriteFileArgs, handler=write_file, mutating=True,
    ))
    registry.register(Tool(
        name="create_file",
        description="Create a new file (parent folders are created automatically).",
        input_model=CreateFileArgs, handler=create_file, mutating=True,
    ))
    registry.register(Tool(
        name="delete_file",
        description="Delete a file. Requires human approval in HITL mode.",
        input_model=DeleteFileArgs, handler=delete_file, mutating=True,
    ))
    registry.register(Tool(
        name="list_files",
        description="List repository files, optionally filtered by folder and suffix.",
        input_model=ListFilesArgs, handler=list_files,
    ))
