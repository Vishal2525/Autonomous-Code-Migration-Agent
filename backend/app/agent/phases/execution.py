"""PHASE 3 — EXECUTION: the only phase allowed to modify source code.

Per task: record pre-SHA → LLM/tool loop applies targeted edits →
git snapshot → MongoDB checkpoint. Any failure rolls the working copy back to
the pre-task SHA so the repository is never left half-migrated by one task.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from app.agent import prompts
from app.agent.agent_loop import FinishTool, run_agent_loop
from app.agent.control import CancelRequested, PauseRequested, SimulatedCrash, check_control
from app.agent.progress import set_phase_progress
from app.config import settings
from app.db.repositories import store
from app.llm.base import AuthError, QuotaExhaustedError
from app.logging_config import get_logger
from app.models.enums import EventType, Phase, TaskStatus
from app.models.schemas import Checkpoint
from app.tools.registry import ApprovalRequiredError, ToolContext

log = get_logger("phase.execution")


class TaskFailure(Exception):
    pass


class CompleteTaskArgs(BaseModel):
    summary: str = Field(min_length=5, description="Short factual summary of what was changed")
    skipped: bool = Field(
        default=False, description="True if the task needed no changes (already done)"
    )


async def run(ctx: ToolContext, llm, registry, run) -> None:
    ctx.phase = Phase.EXECUTION
    tasks = await store.list_tasks(ctx.run_id)
    if not tasks:
        raise TaskFailure("No tasks found — planning did not persist a plan")

    completed_ids = await store.completed_task_ids(ctx.run_id)
    pending = [t for t in tasks if t.task_id not in completed_ids]
    await ctx.emit(
        EventType.PHASE_STARTED,
        f"Executing migration: {len(pending)} of {len(tasks)} tasks remaining",
        {"phase": "EXECUTION"},
    )

    done_count = len(tasks) - len(pending)
    for task in tasks:
        if task.task_id in completed_ids:
            continue
        await check_control(ctx.run_id)

        pre_sha = ctx.git.current_sha()
        ctx.touched_files = set()
        await store.set_task_status(ctx.run_id, task.task_id, TaskStatus.IN_PROGRESS)
        await store.update_run(
            ctx.run_id, current_task_id=task.task_id, current_file=task.file
        )
        await ctx.emit(
            EventType.TASK_STARTED,
            f"{task.task_id}: {task.description}",
            {"task_id": task.task_id, "file": task.file},
        )

        try:
            dep_info = await store.get_dependency(ctx.run_id, task.file)
            file_exists = (ctx.repo_dir / task.file).is_file()
            loop = await run_agent_loop(
                ctx,
                llm,
                registry,
                system_prompt=prompts.execution_system(run, _l1(ctx)),
                user_prompt=prompts.execution_user(task, dep_info, file_exists),
                allow_mutations=True,
                finish_tool=FinishTool(
                    name="complete_task",
                    description="Mark this task as done. Call when all edits are complete.",
                    input_model=CompleteTaskArgs,
                ),
            )
            if not loop.finished:
                raise TaskFailure(
                    "Task loop ended without complete_task: "
                    + "; ".join(loop.errors[-2:] or ["unknown"])
                )

            snapshot = ctx.git.snapshot(f"{task.task_id}: {task.description[:70]}")
            sha = snapshot["sha"]
            if snapshot["committed"]:
                await store.inc_counters(ctx.run_id, git_commits=1)
                changes = ctx.git.diff_names(pre_sha, "HEAD")
                await store.inc_counters(
                    ctx.run_id,
                    files_modified=sum(1 for c in changes if c["status"] == "modified"),
                    files_created=sum(1 for c in changes if c["status"] == "added"),
                    files_deleted=sum(1 for c in changes if c["status"] == "deleted"),
                )
            await store.inc_counters(ctx.run_id, files_processed=1)
            await store.update_run(ctx.run_id, head_sha=sha)

            summary = (loop.finish_args or {}).get("summary", "")
            status = (
                TaskStatus.SKIPPED
                if (loop.finish_args or {}).get("skipped") and not snapshot["committed"]
                else TaskStatus.COMPLETED
            )
            await store.set_task_status(
                ctx.run_id, task.task_id, status, result_summary=summary, git_sha=sha
            )
            await store.save_checkpoint(
                Checkpoint(
                    run_id=ctx.run_id,
                    phase=Phase.EXECUTION,
                    task_id=task.task_id,
                    git_sha=sha,
                    payload={"summary": summary, "file": task.file,
                             "committed": snapshot["committed"]},
                )
            )
            await ctx.emit(
                EventType.CHECKPOINT_CREATED,
                f"Checkpoint: {task.task_id} @ {sha[:10]}",
                {"task_id": task.task_id, "git_sha": sha},
            )
            await ctx.emit(
                EventType.TASK_COMPLETED,
                f"{task.task_id} completed: {summary[:200]}",
                {"task_id": task.task_id, "git_sha": sha},
            )
            done_count += 1
            await set_phase_progress(ctx.run_id, Phase.EXECUTION, done_count / len(tasks))

            # simulated crash AFTER the checkpoint — proves resume skips this task
            if settings.crash_after_task and settings.crash_after_task == task.task_id:
                raise SimulatedCrash(
                    f"CRASH_AFTER_TASK={task.task_id} — simulating a worker crash"
                )

        except (ApprovalRequiredError, PauseRequested, CancelRequested) as exc:
            # discard partial edits; the task re-runs cleanly after approval/resume
            ctx.git.rollback(pre_sha)
            await store.set_task_status(ctx.run_id, task.task_id, TaskStatus.PENDING)
            raise
        except SimulatedCrash:
            raise
        except (AuthError, QuotaExhaustedError):
            ctx.git.rollback(pre_sha)
            await store.set_task_status(ctx.run_id, task.task_id, TaskStatus.PENDING)
            raise
        except Exception as exc:
            ctx.git.rollback(pre_sha)
            await ctx.emit(EventType.GIT_ROLLBACK, f"Rolled back {task.task_id} to {pre_sha[:10]}")
            await store.set_task_status(
                ctx.run_id, task.task_id, TaskStatus.FAILED, error=str(exc)[:1000]
            )
            await store.save_checkpoint(
                Checkpoint(
                    run_id=ctx.run_id,
                    phase=Phase.EXECUTION,
                    task_id=task.task_id,
                    status="failed",
                    git_sha=pre_sha,
                    payload={"error": str(exc)[:500]},
                )
            )
            await ctx.emit(
                EventType.TASK_FAILED,
                f"{task.task_id} failed: {exc}",
                {"task_id": task.task_id},
            )
            log.error("task_failed", task=task.task_id, error=str(exc)[:300])
            # continue with remaining tasks; the repair phase deals with fallout

    await store.update_run(ctx.run_id, current_task_id=None, current_file=None)
    await store.save_checkpoint(
        Checkpoint(run_id=ctx.run_id, phase=Phase.EXECUTION,
                   git_sha=ctx.git.current_sha(), payload={"tasks_total": len(tasks)})
    )
    await set_phase_progress(ctx.run_id, Phase.EXECUTION, 1.0)
    await ctx.emit(EventType.PHASE_COMPLETED, "Execution completed", {"phase": "EXECUTION"})


def _l1(ctx: ToolContext) -> str:
    from app.indexing.summarizer import render_repo_summary

    return render_repo_summary(ctx.index)
