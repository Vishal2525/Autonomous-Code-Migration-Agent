"""Coarse run progress: each phase owns a slice of 0-100%."""
from __future__ import annotations

from app.db.repositories import store
from app.models.enums import Phase

PHASE_RANGES: dict[Phase, tuple[float, float]] = {
    Phase.INDEXING: (0, 15),
    Phase.PLANNING: (15, 30),
    Phase.EXECUTION: (30, 80),
    Phase.REPAIR: (80, 90),
    Phase.VERIFICATION: (90, 100),
}


async def set_phase_progress(run_id: str, phase: Phase, fraction: float) -> None:
    lo, hi = PHASE_RANGES[phase]
    fraction = max(0.0, min(1.0, fraction))
    await store.update_run(run_id, progress=round(lo + (hi - lo) * fraction, 1))
