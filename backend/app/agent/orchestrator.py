"""Agent orchestrator: drives the phase pipeline, checkpoint-aware and re-entrant.

`run_agent(run_id)` can be called on a fresh run OR after a crash/pause/approval;
completed phases are skipped via checkpoints and execution resumes at the first
incomplete task. This is the resume system the whole project is built around.
"""
from __future__ import annotations

import traceback
from functools import partial
from app.llm.groq_provider import GroqProvider
from app.llm.gemini_provider import GeminiProvider
from app.llm.resilience import ResilientLLM

from app.agent.control import (
    CancelRequested,
    PauseRequested,
    SimulatedCrash,
    check_control,
)
from app.agent.gates import check_gate
from app.agent.phases import execution, indexing, planning, repair, verification
from app.agent.state_machine import can_transition
from app.config import settings
from app.db.repositories import store
from app.gitops.manager import GitManager
from app.llm.base import AuthError, QuotaExhaustedError
from app.llm.factory import get_provider
from app.llm.resilience import ResilientLLM
from app.logging_config import get_logger
from app.models.enums import (
    PHASE_ACTIVE_STATE,
    PHASE_ORDER,
    ApprovalGate,
    EventType,
    Phase,
    RunState,
)
from app.models.schemas import Approval, utcnow
from app.services.event_bus import event_bus
from app.tools.builder import build_registry
from app.tools.registry import ApprovalRequiredError, ToolContext

log = get_logger("orchestrator")

#: stale mid-phase statuses bridge through their "phase done" state on resume
_BRIDGE: dict[tuple[RunState, RunState], RunState] = {
    (RunState.INDEXING, RunState.PLANNING): RunState.INDEXED,
    (RunState.PLANNING, RunState.EXECUTING): RunState.PLANNED,
}


async def _enter_phase(run_id: str, phase: Phase) -> None:
    target = PHASE_ACTIVE_STATE[phase]
    run = await store.get_run(run_id)
    if run.status == target:
        await store.update_run(run_id, phase=phase.value)
        return
    if not can_transition(run.status, target):
        bridge = _BRIDGE.get((run.status, target))
        if bridge and can_transition(run.status, bridge) and can_transition(bridge, target):
            await store.set_state(run_id, bridge)
    await store.set_state(run_id, target, phase=phase.value)


async def _restore_git_consistency(ctx: ToolContext) -> None:
    """After a crash the working tree may hold half-applied edits — reset to the
    last checkpointed SHA so the next task starts from known-good state."""
    last = await store.latest_checkpoint(ctx.run_id)
    if last and last.git_sha and ctx.git.has_commit(last.git_sha):
        if ctx.git.is_dirty() or ctx.git.current_sha() != last.git_sha:
            ctx.git.rollback(last.git_sha)
            await ctx.emit(
                EventType.GIT_ROLLBACK,
                f"Restored working copy to last checkpoint {last.git_sha[:10]} after crash",
            )
    elif ctx.git.is_dirty():
        ctx.git.rollback(ctx.git.current_sha())


async def run_agent(run_id: str) -> None:
    run = await store.get_run(run_id)
    if run is None:
        log.error("run_not_found", run_id=run_id)
        return

    workspace = settings.workspace_root / "runs" / run_id
    repo_dir = workspace / "repository"
    workspace.mkdir(parents=True, exist_ok=True)

    emit = partial(event_bus.emit, run_id)

    llm = None
    llm_error = ""
    try:
        groq_provider = GroqProvider(
            api_key=settings.groq_api_key,
            model=settings.groq_model,
        )

        gemini_provider = GeminiProvider(
            api_key=settings.gemini_api_key,
            model=settings.gemini_model,
        )

        llm = ResilientLLM(
            provider=groq_provider,
            fallback_provider=gemini_provider,
        )
        
    except Exception as exc:
        llm_error = str(exc)
        log.warning("llm_unavailable", error=llm_error)

    registry = build_registry()
    ctx = ToolContext(
        run_id=run_id,
        repo_dir=repo_dir,
        workspace_dir=workspace,
        mode=run.mode,
        phase=run.phase or Phase.INDEXING,
        store=store,
        git=None,  # set once the repository exists
        emit=emit,
    )
    for approval in await store.list_approvals(run_id):
        if approval.status == "approved":
            ctx.approved_keys.add(approval.key)

    resumed = (await store.latest_checkpoint(run_id)) is not None
    if run.started_at is None:
        await store.update_run(run_id, started_at=utcnow())
    await emit(
        EventType.RUN_RESUMED if resumed else EventType.RUN_STARTED,
        "Resuming migration from last checkpoint" if resumed else
        f"Starting migration: {run.source_tech} -> {run.target_tech}",
        {"provider": llm.name if llm else None, "model": llm.model if llm else None},
    )

    try:
        # restore context from previous progress (resume path)
        if (repo_dir / ".git").exists():
            ctx.git = GitManager(repo_dir)
            await _restore_git_consistency(ctx)
        index_doc = await store.get_repository_index(run_id)
        if index_doc:
            ctx.index = index_doc

        run = await store.get_run(run_id)
        await check_gate(
            run_id, run.mode, ApprovalGate.BEFORE_MIGRATION, "BEFORE_MIGRATION",
            f"Approve to start migrating {run.repository_url} "
            f"({run.source_tech} -> {run.target_tech}).",
        )

        for phase in PHASE_ORDER:
            if await store.phase_completed(run_id, phase):
                continue
            await check_control(run_id)
            await _enter_phase(run_id, phase)
            ctx.phase = phase
            run = await store.get_run(run_id)

            if phase == Phase.INDEXING:
                await indexing.run(ctx, llm, run)
                await store.set_state(run_id, RunState.INDEXED)
                idx = await store.get_repository_index(run_id)
                await check_gate(
                    run_id, run.mode, ApprovalGate.AFTER_INDEXING, "AFTER_INDEXING",
                    f"Indexing finished: {len(idx.get('files', []))} files, "
                    f"{len(idx.get('folders', []))} source folders. Approve to plan.",
                )
            elif phase == Phase.PLANNING:
                _require_llm(llm, llm_error)
                await planning.run(ctx, llm, registry, run)
                await store.set_state(run_id, RunState.PLANNED)
                tasks = await store.list_tasks(run_id)
                await check_gate(
                    run_id, run.mode, ApprovalGate.AFTER_PLANNING, "AFTER_PLANNING",
                    f"Plan ready with {len(tasks)} tasks. Approve to execute.",
                    data={"tasks": [t.task_id for t in tasks]},
                )
            elif phase == Phase.EXECUTION:
                _require_llm(llm, llm_error)
                await execution.run(ctx, llm, registry, run)
            elif phase == Phase.REPAIR:
                _require_llm(llm, llm_error)
                await repair.run(ctx, llm, registry, run)
            elif phase == Phase.VERIFICATION:
                await verification.run(ctx, run)

        await store.set_state(
            run_id, RunState.COMPLETED, progress=100.0,
            current_task_id=None, current_file=None,
        )
        final = await store.get_run(run_id)
        await emit(
            EventType.RUN_COMPLETED,
            f"Migration completed: {(final.report or {}).get('status', 'DONE')}",
            {"report": final.report},
        )

    except ApprovalRequiredError as exc:
        await store.create_approval(
            Approval(run_id=run_id, gate=exc.gate, key=exc.key,
                     detail=exc.detail, data=exc.data)
        )
        await store.set_state(run_id, RunState.WAITING_FOR_APPROVAL)
        await emit(
            EventType.APPROVAL_REQUIRED, exc.detail,
            {"gate": exc.gate.value, "key": exc.key, **({"data": exc.data} if exc.data else {})},
        )
    except PauseRequested:
        await store.set_state(run_id, RunState.PAUSED, pause_requested=False)
        await emit(EventType.RUN_PAUSED, "Run paused")
    except CancelRequested:
        await store.set_state(
            run_id, RunState.CANCELLED, cancel_requested=False, pause_requested=False
        )
        await emit(EventType.RUN_CANCELLED, "Run cancelled")
    except SimulatedCrash as exc:
        # deliberately do NOT touch run state — this simulates a hard crash;
        # the startup orphan check / resume endpoint recover from it
        log.warning("simulated_crash", run_id=run_id, detail=str(exc))
        raise
    except (AuthError, QuotaExhaustedError) as exc:
        await _fail(run_id, f"LLM provider failure: {exc}")
    except Exception as exc:
        log.error("run_crashed", run_id=run_id, error=repr(exc))
        tb = traceback.format_exc(limit=8)
        await _fail(run_id, f"{exc!r}\n{tb[-1500:]}")


def _require_llm(llm, llm_error: str) -> None:
    if llm is None:
        raise RuntimeError(
            f"LLM provider is not configured: {llm_error or 'set LLM_PROVIDER and an API key'}"
        )


async def _fail(run_id: str, error: str) -> None:
    try:
        await store.set_state(run_id, RunState.FAILED, error=error[:2000])
        await event_bus.emit(
            run_id, EventType.RUN_FAILED,
            f"Run failed: {error[:300]} — fix the cause and use Resume.",
        )
    except Exception:
        log.error("failed_to_mark_failed", run_id=run_id)
