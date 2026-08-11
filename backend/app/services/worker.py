"""Background worker registry.

The API returns immediately; the migration runs as an asyncio task. The worker
entry point (`run_agent`) only takes a run_id and reads all state from MongoDB,
so this registry could be swapped for Celery/RQ/Temporal without touching the
agent itself.
"""
from __future__ import annotations

import asyncio

from app.agent.control import SimulatedCrash
from app.agent.orchestrator import run_agent
from app.db.repositories import store
from app.logging_config import get_logger
from app.models.enums import ACTIVE_STATES, RunState

log = get_logger("worker")


class WorkerRegistry:
    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task] = {}

    def is_active(self, run_id: str) -> bool:
        task = self._tasks.get(run_id)
        return task is not None and not task.done()

    def start(self, run_id: str) -> bool:
        """Spawn the agent worker for a run. Returns False if one is already live."""
        if self.is_active(run_id):
            return False
        task = asyncio.create_task(self._run(run_id), name=f"agent-{run_id[:8]}")
        self._tasks[run_id] = task
        task.add_done_callback(lambda t: self._tasks.pop(run_id, None))
        return True

    async def _run(self, run_id: str) -> None:
        try:
            await run_agent(run_id)
        except SimulatedCrash:
            log.warning(
                "worker_crashed_simulated", run_id=run_id,
                note="run left mid-flight on purpose; use POST /resume",
            )
        except Exception as exc:  # orchestrator normally records failures itself
            log.error("worker_unhandled_error", run_id=run_id, error=repr(exc))


workers = WorkerRegistry()


async def recover_orphaned_runs() -> None:
    """On backend startup: runs stuck in an active state have no live worker
    (hard crash / restart) — mark them FAILED so they can be resumed."""
    for run in await store.list_runs(limit=200):
        if run.status in ACTIVE_STATES and not workers.is_active(run.run_id):
            try:
                await store.set_state(
                    run.run_id, RunState.FAILED,
                    error="Backend restarted while the run was active. "
                          "Use Resume to continue from the last checkpoint.",
                )
                log.info("orphaned_run_marked_failed", run_id=run.run_id)
            except Exception as exc:
                log.error("orphan_recovery_failed", run_id=run.run_id, error=repr(exc))
