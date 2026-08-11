"""Explicit run-state machine. All status changes go through validate_transition."""
from app.models.enums import RunState


class InvalidTransition(Exception):
    def __init__(self, current: RunState, target: RunState):
        self.current = current
        self.target = target
        super().__init__(f"Invalid state transition: {current.value} -> {target.value}")


_ANY_ACTIVE = {
    RunState.INDEXING,
    RunState.INDEXED,
    RunState.PLANNING,
    RunState.PLANNED,
    RunState.EXECUTING,
    RunState.REPAIRING,
    RunState.VERIFYING,
}

TRANSITIONS: dict[RunState, set[RunState]] = {
    RunState.CREATED: {
        RunState.INDEXING,
        RunState.WAITING_FOR_APPROVAL,
        RunState.CANCELLED,
        RunState.FAILED,
    },
    RunState.INDEXING: {
        RunState.INDEXED,
        RunState.WAITING_FOR_APPROVAL,
        RunState.PAUSED,
        RunState.FAILED,
        RunState.CANCELLED,
    },
    RunState.INDEXED: {
        RunState.PLANNING,
        RunState.WAITING_FOR_APPROVAL,
        RunState.PAUSED,
        RunState.FAILED,
        RunState.CANCELLED,
    },
    RunState.PLANNING: {
        RunState.PLANNED,
        RunState.WAITING_FOR_APPROVAL,
        RunState.PAUSED,
        RunState.FAILED,
        RunState.CANCELLED,
    },
    RunState.PLANNED: {
        RunState.EXECUTING,
        RunState.WAITING_FOR_APPROVAL,
        RunState.PAUSED,
        RunState.FAILED,
        RunState.CANCELLED,
    },
    RunState.EXECUTING: {
        RunState.REPAIRING,
        RunState.WAITING_FOR_APPROVAL,
        RunState.PAUSED,
        RunState.FAILED,
        RunState.CANCELLED,
    },
    RunState.REPAIRING: {
        RunState.VERIFYING,
        RunState.EXECUTING,
        RunState.WAITING_FOR_APPROVAL,
        RunState.PAUSED,
        RunState.FAILED,
        RunState.CANCELLED,
    },
    RunState.VERIFYING: {
        RunState.COMPLETED,
        RunState.WAITING_FOR_APPROVAL,
        RunState.PAUSED,
        RunState.FAILED,
        RunState.CANCELLED,
    },
    # Approval can send the run back into whichever phase it gated,
    # or park/kill it.
    RunState.WAITING_FOR_APPROVAL: _ANY_ACTIVE
    | {RunState.PAUSED, RunState.FAILED, RunState.CANCELLED, RunState.COMPLETED},
    # Paused / failed runs resume into the phase they were in.
    RunState.PAUSED: _ANY_ACTIVE | {RunState.FAILED, RunState.CANCELLED},
    RunState.FAILED: _ANY_ACTIVE | {RunState.CANCELLED},
    # Terminal states.
    RunState.CANCELLED: set(),
    RunState.COMPLETED: set(),
}


def can_transition(current: RunState, target: RunState) -> bool:
    return target in TRANSITIONS.get(current, set())


def validate_transition(current: RunState, target: RunState) -> None:
    if not can_transition(current, target):
        raise InvalidTransition(current, target)
