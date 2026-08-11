"""PHASE 4 — REPAIR: run the suite, analyze failures, fix, repeat (bounded).

Attempt budget = MAX_REPAIR_ATTEMPTS per approval cycle. When exhausted, the
run parks in WAITING_FOR_APPROVAL (this gate fires even in AUTO mode);
approving grants another cycle of attempts.

Each attempt is snapshotted; an attempt that INCREASES the failure count is
rolled back before the next attempt starts.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from app.agent import prompts
from app.agent.agent_loop import FinishTool, run_agent_loop
from app.agent.control import check_control
from app.agent.progress import set_phase_progress
from app.config import settings
from app.db.repositories import store
from app.logging_config import get_logger
from app.models.enums import ApprovalGate, EventType, Phase
from app.models.schemas import Checkpoint
from app.tools.registry import ApprovalRequiredError, ToolContext
from app.tools.test_tools import run_tests_impl

log = get_logger("phase.repair")


class CompleteRepairArgs(BaseModel):
    diagnosis: str = Field(min_length=5, description="Root cause of the failures")
    actions: str = Field(min_length=5, description="What was changed to fix them")


def _failure_bundle(ctx: ToolContext, result: dict, run) -> str:
    changed = ctx.git.diff_names(run.baseline_sha) if run.baseline_sha else []
    changed_list = "\n".join(f"- {c['status']}: {c['path']}" for c in changed[:60])
    failing = "\n".join(f"- {t}" for t in result.get("failing_tests", [])[:30])
    return f"""TEST RESULT
Exit code: {result.get('exit_code')} (timed out: {result.get('timed_out')})
Passed: {result.get('passed')}  Failed: {result.get('failed')}  Errors: {result.get('errors')}

FAILING TESTS:
{failing or '- (none listed — see output)'}

FILES CHANGED BY THE MIGRATION SO FAR:
{changed_list or '- (none)'}

TEST OUTPUT (tail):
{result.get('output', '')[-9000:]}"""


async def run(ctx: ToolContext, llm, registry, run) -> None:
    ctx.phase = Phase.REPAIR
    await ctx.emit(EventType.PHASE_STARTED, "Repair phase: running test suite",
                   {"phase": "REPAIR"})

    # resume support: attempts already made + approval cycles granted
    checkpoints = await store.list_checkpoints(ctx.run_id)
    attempt = sum(
        1 for c in checkpoints
        if c.phase == Phase.REPAIR and c.task_id and c.task_id.startswith("REPAIR-")
    )
    approvals = await store.list_approvals(ctx.run_id)
    cycles = sum(
        1 for a in approvals
        if a.gate == ApprovalGate.REPAIR_EXHAUSTED and a.status == "approved"
    )
    budget = settings.max_repair_attempts * (cycles + 1)

    last_pre_sha: str | None = None
    last_failure_count: int | None = None

    while True:
        await check_control(ctx.run_id)
        result = await run_tests_impl(ctx, [], attempt=attempt)
        failures_now = result["failed"] + result["errors"]

        # if the previous attempt made things WORSE, roll it back
        if (
            last_pre_sha is not None
            and last_failure_count is not None
            and failures_now > last_failure_count
        ):
            ctx.git.rollback(last_pre_sha)
            await ctx.emit(
                EventType.GIT_ROLLBACK,
                f"Repair attempt increased failures ({last_failure_count} -> "
                f"{failures_now}); rolled back to {last_pre_sha[:10]}",
            )
            failures_now = last_failure_count
            last_pre_sha = None
            last_failure_count = None
            # re-run to get accurate failure evidence for the next attempt
            result = await run_tests_impl(ctx, [], attempt=attempt)
            failures_now = result["failed"] + result["errors"]

        if result["success"]:
            await store.save_checkpoint(
                Checkpoint(run_id=ctx.run_id, phase=Phase.REPAIR,
                           git_sha=ctx.git.current_sha(),
                           payload={"attempts": attempt, "passed": result["passed"]})
            )
            await set_phase_progress(ctx.run_id, Phase.REPAIR, 1.0)
            await ctx.emit(
                EventType.PHASE_COMPLETED,
                f"Repair complete after {attempt} attempt(s): "
                f"{result['passed']} tests passing",
                {"phase": "REPAIR"},
            )
            return

        if attempt >= budget:
            raise ApprovalRequiredError(
                gate=ApprovalGate.REPAIR_EXHAUSTED,
                key=f"REPAIR_EXHAUSTED:{budget}",
                detail=(
                    f"Repair attempts exhausted ({attempt}/{budget}). "
                    f"Still failing: {failures_now} tests. "
                    "Approve to grant another repair cycle, or reject to pause."
                ),
                data={"failing_tests": result.get("failing_tests", [])[:20]},
            )

        attempt += 1
        await store.inc_counters(ctx.run_id, repair_attempts=1)
        await ctx.emit(
            EventType.REPAIR_STARTED if attempt == 1 else EventType.REPAIR_ATTEMPT,
            f"Repair attempt {attempt}/{budget}: {failures_now} failing",
            {"attempt": attempt, "failing": failures_now},
        )

        last_pre_sha = ctx.git.current_sha()
        last_failure_count = failures_now
        ctx.touched_files = set()

        from app.indexing.summarizer import render_repo_summary

        loop = await run_agent_loop(
            ctx,
            llm,
            registry,
            system_prompt=prompts.repair_system(run, render_repo_summary(ctx.index)),
            user_prompt=prompts.repair_user(
                attempt, budget, _failure_bundle(ctx, result, run)
            ),
            allow_mutations=True,
            finish_tool=FinishTool(
                name="complete_repair",
                description="Finish this repair attempt with your diagnosis and actions.",
                input_model=CompleteRepairArgs,
            ),
        )
        snapshot = ctx.git.snapshot(f"Repair attempt {attempt}")
        if snapshot["committed"]:
            await store.inc_counters(ctx.run_id, git_commits=1)
            await store.update_run(ctx.run_id, head_sha=snapshot["sha"])
        await store.save_checkpoint(
            Checkpoint(
                run_id=ctx.run_id,
                phase=Phase.REPAIR,
                task_id=f"REPAIR-{attempt}",
                git_sha=snapshot["sha"],
                payload={
                    "diagnosis": (loop.finish_args or {}).get("diagnosis", "")[:500],
                    "actions": (loop.finish_args or {}).get("actions", "")[:500],
                    "finished": loop.finished,
                },
            )
        )
        await ctx.emit(EventType.CHECKPOINT_CREATED, f"Repair attempt {attempt} checkpointed")
        await set_phase_progress(
            ctx.run_id, Phase.REPAIR, min(0.9, attempt / (budget + 1))
        )
