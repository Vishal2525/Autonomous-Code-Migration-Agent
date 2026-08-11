"""MongoDB-backed tests for checkpointing + resume-point resolution.

Uses a throwaway database on the local MongoDB instance; skipped when
MongoDB is unreachable.
"""
import pytest

from app.agent.state_machine import InvalidTransition
from app.db import mongo
from app.db.repositories import Store
from app.models.enums import ApprovalGate, Phase, RunState
from app.models.schemas import Approval, Checkpoint, Run

TEST_DB = "migration_agent_test"


@pytest.fixture()
async def db_store():
    try:
        db = await mongo.connect(TEST_DB)
    except Exception:
        pytest.skip("MongoDB is not reachable")
    store = Store()
    store.bind(db)
    yield store
    client = db.client
    await client.drop_database(TEST_DB)
    await mongo.close()


def _run(run_id="run-test-1") -> Run:
    return Run(
        run_id=run_id,
        repository_url="https://github.com/example/demo",
        goal="migrate",
        source_tech="Flask",
        target_tech="FastAPI",
    )


async def test_run_roundtrip(db_store):
    await db_store.create_run(_run())
    run = await db_store.get_run("run-test-1")
    assert run is not None
    assert run.status == RunState.CREATED
    assert run.counters.files_indexed == 0


async def test_set_state_validates_transitions(db_store):
    await db_store.create_run(_run())
    run = await db_store.set_state("run-test-1", RunState.INDEXING)
    assert run.status == RunState.INDEXING
    with pytest.raises(InvalidTransition):
        await db_store.set_state("run-test-1", RunState.COMPLETED)


async def test_phase_checkpoints_drive_resume_skipping(db_store):
    await db_store.create_run(_run())
    assert not await db_store.phase_completed("run-test-1", Phase.INDEXING)
    await db_store.save_checkpoint(
        Checkpoint(run_id="run-test-1", phase=Phase.INDEXING, git_sha="a" * 40)
    )
    assert await db_store.phase_completed("run-test-1", Phase.INDEXING)
    assert not await db_store.phase_completed("run-test-1", Phase.PLANNING)


async def test_completed_task_ids_resume_point(db_store):
    """The crash/resume core: after TASK-001/002 checkpoint, resume = TASK-003."""
    await db_store.create_run(_run())
    for task_id in ("TASK-001", "TASK-002"):
        await db_store.save_checkpoint(
            Checkpoint(run_id="run-test-1", phase=Phase.EXECUTION,
                       task_id=task_id, git_sha="b" * 40)
        )
    # a FAILED task checkpoint must NOT count as completed
    await db_store.save_checkpoint(
        Checkpoint(run_id="run-test-1", phase=Phase.EXECUTION,
                   task_id="TASK-003", status="failed", git_sha="c" * 40)
    )
    done = await db_store.completed_task_ids("run-test-1")
    assert done == {"TASK-001", "TASK-002"}

    all_tasks = ["TASK-001", "TASK-002", "TASK-003", "TASK-004"]
    remaining = [t for t in all_tasks if t not in done]
    assert remaining == ["TASK-003", "TASK-004"]


async def test_latest_checkpoint_orders_correctly(db_store):
    await db_store.create_run(_run())
    for i, task in enumerate(["TASK-001", "TASK-002"]):
        await db_store.save_checkpoint(
            Checkpoint(run_id="run-test-1", phase=Phase.EXECUTION,
                       task_id=task, git_sha=str(i) * 40)
        )
    latest = await db_store.latest_checkpoint("run-test-1")
    assert latest is not None and latest.task_id == "TASK-002"


async def test_approval_lifecycle(db_store):
    await db_store.create_run(_run())
    approval = Approval(
        run_id="run-test-1", gate=ApprovalGate.AFTER_PLANNING,
        key="AFTER_PLANNING", detail="approve the plan",
    )
    await db_store.create_approval(approval)
    pending = await db_store.pending_approval("run-test-1")
    assert pending is not None and pending.key == "AFTER_PLANNING"

    await db_store.resolve_approval("run-test-1", "AFTER_PLANNING", "approved")
    assert await db_store.pending_approval("run-test-1") is None
    resolved = await db_store.get_approval("run-test-1", "AFTER_PLANNING")
    assert resolved.status == "approved"

    # re-arming a rejected gate flips it back to pending
    await db_store.resolve_approval("run-test-1", "AFTER_PLANNING", "rejected")
    await db_store.create_approval(approval)
    assert (await db_store.get_approval("run-test-1", "AFTER_PLANNING")).status == "pending"


async def test_counters_and_usage_accumulate(db_store):
    await db_store.create_run(_run())
    await db_store.inc_counters("run-test-1", files_modified=2, git_commits=1)
    await db_store.add_llm_usage("run-test-1", 1000, 200)
    await db_store.add_llm_usage("run-test-1", 500, 100)
    run = await db_store.get_run("run-test-1")
    assert run.counters.files_modified == 2
    assert run.llm_usage.calls == 2
    assert run.llm_usage.total_tokens == 1800
