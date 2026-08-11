"""Typed CRUD facade over MongoDB collections.

All documents are stored via Pydantic ``model_dump()`` — the str-based enums and
native datetimes encode directly to BSON. Reads are parsed back through the
Pydantic models so the rest of the app never touches raw dicts for core types.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.agent.state_machine import validate_transition
from app.models.enums import ApprovalGate, Phase, RunState, TaskStatus
from app.models.schemas import (
    Approval,
    Checkpoint,
    Event,
    MigrationPlan,
    PlanTask,
    Run,
    TestRunRecord,
    utcnow,
)


class Store:
    def __init__(self) -> None:
        self._db: AsyncIOMotorDatabase | None = None

    def bind(self, db: AsyncIOMotorDatabase) -> None:
        self._db = db

    @property
    def db(self) -> AsyncIOMotorDatabase:
        if self._db is None:
            raise RuntimeError("Store is not bound to a database")
        return self._db

    # ── runs ──────────────────────────────────────────────────────────

    async def create_run(self, run: Run) -> Run:
        await self.db.runs.insert_one(run.model_dump())
        return run

    async def get_run(self, run_id: str) -> Run | None:
        doc = await self.db.runs.find_one({"run_id": run_id})
        return Run(**doc) if doc else None

    async def list_runs(self, limit: int = 100) -> list[Run]:
        docs = await self.db.runs.find().sort("created_at", -1).to_list(limit)
        return [Run(**d) for d in docs]

    async def update_run(self, run_id: str, **fields: Any) -> None:
        fields["updated_at"] = utcnow()
        await self.db.runs.update_one({"run_id": run_id}, {"$set": fields})

    async def set_state(self, run_id: str, target: RunState, **extra: Any) -> Run:
        """Validated state transition; raises InvalidTransition otherwise."""
        run = await self.get_run(run_id)
        if run is None:
            raise ValueError(f"Run {run_id} not found")
        validate_transition(run.status, target)
        fields: dict[str, Any] = {"status": target, "updated_at": utcnow(), **extra}
        if target in (RunState.COMPLETED, RunState.FAILED, RunState.CANCELLED):
            fields.setdefault("finished_at", utcnow())
        await self.db.runs.update_one({"run_id": run_id}, {"$set": fields})
        run = await self.get_run(run_id)
        assert run is not None
        return run

    async def inc_counters(self, run_id: str, **inc: int) -> None:
        await self.db.runs.update_one(
            {"run_id": run_id},
            {
                "$inc": {f"counters.{k}": v for k, v in inc.items()},
                "$set": {"updated_at": utcnow()},
            },
        )

    async def add_llm_usage(
        self, run_id: str, prompt_tokens: int, completion_tokens: int
    ) -> None:
        await self.db.runs.update_one(
            {"run_id": run_id},
            {
                "$inc": {
                    "llm_usage.calls": 1,
                    "llm_usage.prompt_tokens": prompt_tokens,
                    "llm_usage.completion_tokens": completion_tokens,
                    "llm_usage.total_tokens": prompt_tokens + completion_tokens,
                },
                "$set": {"updated_at": utcnow()},
            },
        )

    # ── checkpoints ───────────────────────────────────────────────────

    async def save_checkpoint(self, cp: Checkpoint) -> None:
        await self.db.checkpoints.insert_one(cp.model_dump())

    async def latest_checkpoint(self, run_id: str) -> Checkpoint | None:
        doc = await self.db.checkpoints.find_one(
            {"run_id": run_id}, sort=[("created_at", -1), ("_id", -1)]
        )
        return Checkpoint(**doc) if doc else None

    async def phase_completed(self, run_id: str, phase: Phase) -> bool:
        doc = await self.db.checkpoints.find_one(
            {"run_id": run_id, "phase": phase.value, "task_id": None, "status": "completed"}
        )
        return doc is not None

    async def completed_task_ids(self, run_id: str) -> set[str]:
        cursor = self.db.checkpoints.find(
            {"run_id": run_id, "phase": Phase.EXECUTION.value, "status": "completed",
             "task_id": {"$ne": None}},
            {"task_id": 1},
        )
        return {d["task_id"] async for d in cursor}

    async def list_checkpoints(self, run_id: str, limit: int = 500) -> list[Checkpoint]:
        docs = (
            await self.db.checkpoints.find({"run_id": run_id})
            .sort([("created_at", 1), ("_id", 1)])
            .to_list(limit)
        )
        return [Checkpoint(**d) for d in docs]

    # ── events ────────────────────────────────────────────────────────

    async def add_event(self, ev: Event) -> dict[str, Any]:
        doc = ev.model_dump()
        result = await self.db.events.insert_one(doc)
        doc["id"] = str(result.inserted_id)
        doc.pop("_id", None)
        return doc

    async def list_events(
        self, run_id: str, after_id: str | None = None, limit: int = 200
    ) -> list[dict[str, Any]]:
        query: dict[str, Any] = {"run_id": run_id}
        if after_id:
            query["_id"] = {"$gt": ObjectId(after_id)}
        docs = await self.db.events.find(query).sort("_id", 1).to_list(limit)
        for d in docs:
            d["id"] = str(d.pop("_id"))
        return docs

    async def recent_events(self, run_id: str, limit: int = 100) -> list[dict[str, Any]]:
        docs = await self.db.events.find({"run_id": run_id}).sort("_id", -1).to_list(limit)
        docs.reverse()
        for d in docs:
            d["id"] = str(d.pop("_id"))
        return docs

    # ── plans & tasks ─────────────────────────────────────────────────

    async def save_plan(self, plan: MigrationPlan) -> None:
        doc = plan.model_dump(exclude={"tasks"})
        doc["task_ids"] = [t.task_id for t in plan.tasks]
        await self.db.plans.replace_one({"run_id": plan.run_id}, doc, upsert=True)
        for task in plan.tasks:
            await self.db.tasks.replace_one(
                {"run_id": plan.run_id, "task_id": task.task_id},
                task.model_dump(),
                upsert=True,
            )

    async def get_plan(self, run_id: str) -> dict[str, Any] | None:
        doc = await self.db.plans.find_one({"run_id": run_id}, {"_id": 0})
        return doc

    async def list_tasks(self, run_id: str) -> list[PlanTask]:
        docs = await self.db.tasks.find({"run_id": run_id}).sort("priority", 1).to_list(1000)
        return [PlanTask(**d) for d in docs]

    async def get_task(self, run_id: str, task_id: str) -> PlanTask | None:
        doc = await self.db.tasks.find_one({"run_id": run_id, "task_id": task_id})
        return PlanTask(**doc) if doc else None

    async def update_task(self, run_id: str, task_id: str, **fields: Any) -> None:
        fields["updated_at"] = utcnow()
        await self.db.tasks.update_one(
            {"run_id": run_id, "task_id": task_id}, {"$set": fields}
        )

    async def set_task_status(
        self, run_id: str, task_id: str, status: TaskStatus, **fields: Any
    ) -> None:
        await self.update_task(run_id, task_id, status=status, **fields)

    # ── test results ──────────────────────────────────────────────────

    async def add_test_result(self, rec: TestRunRecord) -> None:
        await self.db.test_results.insert_one(rec.model_dump())

    async def list_test_results(self, run_id: str) -> list[TestRunRecord]:
        docs = (
            await self.db.test_results.find({"run_id": run_id})
            .sort([("created_at", 1), ("_id", 1)])
            .to_list(200)
        )
        return [TestRunRecord(**d) for d in docs]

    async def latest_test_result(self, run_id: str) -> TestRunRecord | None:
        doc = await self.db.test_results.find_one(
            {"run_id": run_id}, sort=[("created_at", -1), ("_id", -1)]
        )
        return TestRunRecord(**doc) if doc else None

    # ── approvals ─────────────────────────────────────────────────────

    async def create_approval(self, approval: Approval) -> None:
        existing = await self.db.approvals.find_one(
            {"run_id": approval.run_id, "key": approval.key}
        )
        if existing is None:
            await self.db.approvals.insert_one(approval.model_dump())
        elif existing["status"] == "rejected":
            # gate re-armed after a rejection → back to pending
            await self.db.approvals.update_one(
                {"run_id": approval.run_id, "key": approval.key},
                {"$set": {"status": "pending", "detail": approval.detail,
                          "data": approval.data, "resolved_at": None}},
            )

    async def get_approval(self, run_id: str, key: str) -> Approval | None:
        doc = await self.db.approvals.find_one({"run_id": run_id, "key": key})
        return Approval(**doc) if doc else None

    async def pending_approval(self, run_id: str) -> Approval | None:
        doc = await self.db.approvals.find_one({"run_id": run_id, "status": "pending"})
        return Approval(**doc) if doc else None

    async def resolve_approval(self, run_id: str, key: str, status: str) -> None:
        await self.db.approvals.update_one(
            {"run_id": run_id, "key": key},
            {"$set": {"status": status, "resolved_at": utcnow()}},
        )

    async def list_approvals(self, run_id: str) -> list[Approval]:
        docs = await self.db.approvals.find({"run_id": run_id}).to_list(100)
        return [Approval(**d) for d in docs]

    # ── repository index data ─────────────────────────────────────────

    async def save_repository_index(self, doc: dict[str, Any]) -> None:
        await self.db.repository_indexes.replace_one(
            {"run_id": doc["run_id"]}, doc, upsert=True
        )

    async def get_repository_index(self, run_id: str) -> dict[str, Any] | None:
        return await self.db.repository_indexes.find_one({"run_id": run_id}, {"_id": 0})

    async def save_files(self, run_id: str, files: list[dict[str, Any]]) -> None:
        await self.db.files.delete_many({"run_id": run_id})
        if files:
            for f in files:
                f["run_id"] = run_id
            await self.db.files.insert_many(files)

    async def list_files(self, run_id: str) -> list[dict[str, Any]]:
        return await self.db.files.find({"run_id": run_id}, {"_id": 0}).to_list(10000)

    async def get_file(self, run_id: str, path: str) -> dict[str, Any] | None:
        return await self.db.files.find_one({"run_id": run_id, "path": path}, {"_id": 0})

    async def save_dependencies(self, run_id: str, deps: list[dict[str, Any]]) -> None:
        await self.db.dependencies.delete_many({"run_id": run_id})
        if deps:
            for d in deps:
                d["run_id"] = run_id
            await self.db.dependencies.insert_many(deps)

    async def list_dependencies(self, run_id: str) -> list[dict[str, Any]]:
        return await self.db.dependencies.find({"run_id": run_id}, {"_id": 0}).to_list(10000)

    async def get_dependency(self, run_id: str, source_file: str) -> dict[str, Any] | None:
        return await self.db.dependencies.find_one(
            {"run_id": run_id, "source_file": source_file}, {"_id": 0}
        )


#: process-wide singleton, bound in app lifespan (or tests)
store = Store()
