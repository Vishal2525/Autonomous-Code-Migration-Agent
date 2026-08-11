"""Human-in-the-loop gate checks.

A gate either passes silently (AUTO mode / already approved) or raises
ApprovalRequiredError, which the orchestrator turns into a pending approval +
WAITING_FOR_APPROVAL state. After the user approves, the worker re-enters the
orchestrator and the same gate check passes.
"""
from __future__ import annotations

from typing import Any

from app.db.repositories import store
from app.models.enums import ALWAYS_ON_GATES, ApprovalGate, RunMode
from app.tools.registry import ApprovalRequiredError


async def check_gate(
    run_id: str,
    mode: RunMode,
    gate: ApprovalGate,
    key: str,
    detail: str,
    data: dict[str, Any] | None = None,
) -> None:
    if mode == RunMode.AUTO and gate not in ALWAYS_ON_GATES:
        return
    approval = await store.get_approval(run_id, key)
    if approval is not None and approval.status == "approved":
        return
    raise ApprovalRequiredError(gate=gate, key=key, detail=detail, data=data)
