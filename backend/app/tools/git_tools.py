"""Git tools exposed to the agent: status, diff, snapshot, rollback, log."""
from __future__ import annotations

from pydantic import BaseModel, Field

from app.models.enums import EventType
from app.tools.registry import Tool, ToolContext, ToolError, ToolRegistry


class EmptyArgs(BaseModel):
    pass


class DiffArgs(BaseModel):
    base: str | None = Field(
        default=None,
        description="Base commit SHA (defaults to the run's baseline commit)",
    )
    path: str | None = Field(default=None, description="Limit the diff to one file")


class SnapshotArgs(BaseModel):
    message: str = Field(min_length=3, description="Commit message for the snapshot")


class RollbackArgs(BaseModel):
    sha: str = Field(min_length=6, description="Commit SHA to hard-reset to")


class LogArgs(BaseModel):
    n: int = Field(default=10, ge=1, le=50)


async def git_status(ctx: ToolContext, args: EmptyArgs):
    status = ctx.git.status()
    return {"clean": status == "", "status": status or "working tree clean",
            "head": ctx.git.current_sha()}


async def git_diff(ctx: ToolContext, args: DiffArgs):
    run = await ctx.store.get_run(ctx.run_id)
    base = args.base or (run.baseline_sha if run else None)
    if not base:
        raise ToolError("No base SHA available for diff")
    committed = ctx.git.diff_patch(base, "HEAD", path=args.path, max_chars=30000)
    working = ctx.git.working_diff(max_chars=15000)
    return {"base": base, "committed_diff": committed, "uncommitted_diff": working}


async def git_snapshot(ctx: ToolContext, args: SnapshotArgs):
    result = ctx.git.snapshot(args.message)
    if result["committed"]:
        await ctx.emit(
            EventType.GIT_SNAPSHOT,
            f"Snapshot: {args.message}",
            {"sha": result["sha"]},
        )
        await ctx.store.inc_counters(ctx.run_id, git_commits=1)
        await ctx.store.update_run(ctx.run_id, head_sha=result["sha"])
    return result


async def git_rollback(ctx: ToolContext, args: RollbackArgs):
    if not ctx.git.has_commit(args.sha):
        raise ToolError(f"Unknown commit: {args.sha}")
    sha = ctx.git.rollback(args.sha)
    await ctx.emit(EventType.GIT_ROLLBACK, f"Rolled back to {sha[:10]}", {"sha": sha})
    await ctx.store.update_run(ctx.run_id, head_sha=sha)
    return {"head": sha}


async def git_log(ctx: ToolContext, args: LogArgs):
    return {"commits": ctx.git.log_entries(args.n)}


def register_git_tools(registry: ToolRegistry) -> None:
    registry.register(Tool(
        name="git_status",
        description="Current git status (clean/dirty) and HEAD SHA of the working copy.",
        input_model=EmptyArgs, handler=git_status,
    ))
    registry.register(Tool(
        name="git_diff",
        description="Diff against the migration baseline (or a given base commit).",
        input_model=DiffArgs, handler=git_diff,
    ))
    registry.register(Tool(
        name="git_snapshot",
        description="Commit all current changes as a snapshot. Returns the new SHA.",
        input_model=SnapshotArgs, handler=git_snapshot, mutating=True,
    ))
    registry.register(Tool(
        name="git_rollback",
        description="Hard-reset the working copy to a previous snapshot SHA "
                    "(discards all changes after it).",
        input_model=RollbackArgs, handler=git_rollback, mutating=True,
    ))
    registry.register(Tool(
        name="git_log",
        description="Recent commits on the migration branch.",
        input_model=LogArgs, handler=git_log,
    ))
