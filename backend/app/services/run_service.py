"""Run lifecycle operations — state-machine guarded, worker-aware."""
from __future__ import annotations

import uuid
from pathlib import Path

from app.db.repositories import store
from app.logging_config import get_logger
from app.models.enums import ACTIVE_STATES, TERMINAL_STATES, EventType, RunState
from app.models.schemas import Run, RunCreate
from app.services.event_bus import event_bus
from app.services.worker import workers

log = get_logger("service.runs")


class ServiceError(Exception):
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message
        super().__init__(message)


async def _get_or_404(run_id: str) -> Run:
    run = await store.get_run(run_id)
    if run is None:
        raise ServiceError(404, f"Run {run_id} not found")
    return run


def _validate_repository_url(url: str) -> None:
    url = url.strip()
    if url.startswith(("http://", "https://", "git@", "ssh://", "file://")):
        return
    if Path(url).is_dir():
        return
    raise ServiceError(
        422,
        "repository_url must be an http(s)/git remote URL or an existing local directory",
    )


async def create_run(payload: RunCreate) -> Run:
    _validate_repository_url(payload.repository_url)
    run = Run(
        run_id=uuid.uuid4().hex[:12],
        repository_url=payload.repository_url.strip(),
        goal=payload.goal.strip(),
        source_tech=payload.source_tech.strip(),
        target_tech=payload.target_tech.strip(),
        mode=payload.mode,
    )
    await store.create_run(run)
    await event_bus.emit(
        run.run_id, EventType.RUN_CREATED,
        f"Run created for {run.repository_url} ({run.source_tech} -> {run.target_tech}, "
        f"mode {run.mode.value})",
    )
    return run


async def start_run(run_id: str) -> Run:
    run = await _get_or_404(run_id)
    if run.status != RunState.CREATED:
        raise ServiceError(
            409, f"Run is {run.status.value} — use resume for interrupted runs"
        )
    if not workers.start(run_id):
        raise ServiceError(409, "A worker is already active for this run")
    return await _get_or_404(run_id)


async def pause_run(run_id: str) -> Run:
    run = await _get_or_404(run_id)
    if run.status == RunState.WAITING_FOR_APPROVAL:
        # no worker is live — park it directly
        return await store.set_state(run_id, RunState.PAUSED)
    if run.status not in ACTIVE_STATES:
        raise ServiceError(409, f"Cannot pause a {run.status.value} run")
    await store.update_run(run_id, pause_requested=True)
    return await _get_or_404(run_id)


async def resume_run(run_id: str) -> Run:
    run = await _get_or_404(run_id)
    if run.status in TERMINAL_STATES:
        raise ServiceError(409, f"Run is {run.status.value} and cannot be resumed")
    if run.status == RunState.WAITING_FOR_APPROVAL:
        raise ServiceError(409, "Run is waiting for approval — approve or reject it")
    if run.status in ACTIVE_STATES and workers.is_active(run_id):
        raise ServiceError(409, "Run is already being executed")
    if run.status == RunState.CREATED:
        raise ServiceError(409, "Run has not started yet — use start")
    # PAUSED / FAILED / stale-active-after-crash all resume here
    await store.update_run(
        run_id, pause_requested=False, cancel_requested=False, error=None
    )
    workers.start(run_id)
    return await _get_or_404(run_id)


async def approve_run(run_id: str) -> Run:
    run = await _get_or_404(run_id)
    if run.status != RunState.WAITING_FOR_APPROVAL:
        raise ServiceError(409, f"Run is {run.status.value}, not waiting for approval")
    approval = await store.pending_approval(run_id)
    if approval is None:
        raise ServiceError(409, "No pending approval found")
    await store.resolve_approval(run_id, approval.key, "approved")
    await event_bus.emit(
        run_id, EventType.APPROVAL_GRANTED,
        f"Approved: {approval.gate.value}", {"key": approval.key},
    )
    workers.start(run_id)
    return await _get_or_404(run_id)


async def reject_run(run_id: str) -> Run:
    run = await _get_or_404(run_id)
    if run.status != RunState.WAITING_FOR_APPROVAL:
        raise ServiceError(409, f"Run is {run.status.value}, not waiting for approval")
    approval = await store.pending_approval(run_id)
    if approval is not None:
        await store.resolve_approval(run_id, approval.key, "rejected")
        await event_bus.emit(
            run_id, EventType.APPROVAL_REJECTED,
            f"Rejected: {approval.gate.value} — run paused", {"key": approval.key},
        )
    updated = await store.set_state(run_id, RunState.PAUSED)
    await event_bus.emit(run_id, EventType.RUN_PAUSED, "Run paused after rejection")
    return updated


async def cancel_run(run_id: str) -> Run:
    run = await _get_or_404(run_id)
    if run.status in TERMINAL_STATES:
        raise ServiceError(409, f"Run is already {run.status.value}")
    if run.status in ACTIVE_STATES and workers.is_active(run_id):
        await store.update_run(run_id, cancel_requested=True)  # cooperative
        return await _get_or_404(run_id)
    updated = await store.set_state(run_id, RunState.CANCELLED)
    await event_bus.emit(run_id, EventType.RUN_CANCELLED, "Run cancelled")
    return updated
