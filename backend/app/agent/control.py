"""Cooperative control-flow signals for the agent worker."""
from __future__ import annotations

from app.db.repositories import store


class PauseRequested(Exception):
    pass


class CancelRequested(Exception):
    pass


class SimulatedCrash(Exception):
    """Raised by CRASH_AFTER_TASK to prove the resume system works."""


async def check_control(run_id: str) -> None:
    """Called between tasks / loop iterations — honors pause & cancel flags from Mongo."""
    run = await store.get_run(run_id)
    if run is None:
        raise CancelRequested()
    if run.cancel_requested:
        raise CancelRequested()
    if run.pause_requested:
        raise PauseRequested()
