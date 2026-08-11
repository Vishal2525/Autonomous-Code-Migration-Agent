import pytest

from app.agent.state_machine import InvalidTransition, can_transition, validate_transition
from app.models.enums import RunState as S


def test_happy_path_transitions():
    path = [
        (S.CREATED, S.INDEXING),
        (S.INDEXING, S.INDEXED),
        (S.INDEXED, S.PLANNING),
        (S.PLANNING, S.PLANNED),
        (S.PLANNED, S.EXECUTING),
        (S.EXECUTING, S.REPAIRING),
        (S.REPAIRING, S.VERIFYING),
        (S.VERIFYING, S.COMPLETED),
    ]
    for current, target in path:
        validate_transition(current, target)  # should not raise


def test_invalid_transitions_rejected():
    for current, target in [
        (S.CREATED, S.EXECUTING),
        (S.CREATED, S.COMPLETED),
        (S.COMPLETED, S.EXECUTING),
        (S.CANCELLED, S.INDEXING),
        (S.INDEXING, S.VERIFYING),
        (S.EXECUTING, S.INDEXING),
    ]:
        with pytest.raises(InvalidTransition):
            validate_transition(current, target)


def test_resume_transitions():
    assert can_transition(S.FAILED, S.EXECUTING)
    assert can_transition(S.PAUSED, S.REPAIRING)
    assert can_transition(S.WAITING_FOR_APPROVAL, S.PLANNING)
    assert can_transition(S.WAITING_FOR_APPROVAL, S.PAUSED)
    assert not can_transition(S.COMPLETED, S.EXECUTING)


def test_pause_and_cancel_from_active():
    for state in (S.INDEXING, S.PLANNING, S.EXECUTING, S.REPAIRING, S.VERIFYING):
        assert can_transition(state, S.PAUSED) or state is S.CREATED
        assert can_transition(state, S.CANCELLED)
        assert can_transition(state, S.FAILED)
