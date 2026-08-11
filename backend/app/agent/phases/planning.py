"""PHASE 2 — PLANNING: read-only agent loop that produces a structured plan.

The planner may inspect the repository with read-only tools but can never
modify it — the registry rejects mutating tools while allow_mutations=False.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from app.agent import context_builder, prompts
from app.agent.agent_loop import FinishTool, run_agent_loop
from app.agent.progress import set_phase_progress
from app.db.repositories import store
from app.logging_config import get_logger
from app.models.enums import EventType, Phase, TaskStatus
from app.models.schemas import Checkpoint, MigrationPlan, PlanTask
from app.tools.registry import ToolContext

log = get_logger("phase.planning")


class PhaseError(Exception):
    pass


class TaskSubmission(BaseModel):
    task_id: str | None = Field(default=None, description="Optional id; will be normalized")
    file: str = Field(description="Repository-relative file this task changes or creates")
    description: str = Field(description="What this task accomplishes (one sentence)")
    reason: str = Field(default="", description="Why this change is needed for the migration")
    instructions: str = Field(
        description="Concrete, self-contained migration instructions for the executor"
    )
    dependencies: list[str] = Field(
        default_factory=list, description="Files this task's file depends on"
    )
    expected_changes: list[str] = Field(
        default_factory=list, description="Bullet list of expected concrete changes"
    )
    validation: str = Field(default="", description="How to verify this task succeeded")
    priority: int = Field(default=100, ge=1, description="Lower = executed earlier")


class PlanSubmission(BaseModel):
    migration: str = Field(description="e.g. 'Flask -> FastAPI'")
    overview: str = Field(default="", description="Short strategy summary")
    tasks: list[TaskSubmission] = Field(min_length=1)


async def run(ctx: ToolContext, llm, registry, run) -> None:
    ctx.phase = Phase.PLANNING
    await ctx.emit(EventType.PHASE_STARTED, "Planning migration", {"phase": "PLANNING"})

    l1 = context_builder.level1(ctx.index)
    l2 = context_builder.level2_all(ctx.index)
    dep_docs = await store.list_dependencies(ctx.run_id)
    dep_digest = context_builder.dependency_graph_digest(dep_docs)
    dep_files = context_builder.dependency_file_contents(ctx.index, ctx.repo_dir)

    baseline = await store.latest_test_result(ctx.run_id)
    baseline_text = (
        f"{baseline.passed} passed, {baseline.failed} failed, {baseline.errors} errors "
        f"(exit {baseline.exit_code})" if baseline else "not available"
    )

    loop = await run_agent_loop(
        ctx,
        llm,
        registry,
        system_prompt=prompts.planning_system(run, l1),
        user_prompt=prompts.planning_user(l2, dep_digest, dep_files, baseline_text),
        allow_mutations=False,  # planning must never touch the repository
        finish_tool=FinishTool(
            name="submit_plan",
            description="Submit the final migration plan. Call exactly once, when done inspecting.",
            input_model=PlanSubmission,
        ),
        max_iterations=20,
    )
    if not loop.finished or not loop.finish_args:
        raise PhaseError(
            "Planner did not produce a plan: " + "; ".join(loop.errors[-3:] or ["no output"])
        )

    submission = PlanSubmission(**loop.finish_args)

    # normalize: stable ordering by priority, sequential ids
    ordered = sorted(enumerate(submission.tasks), key=lambda it: (it[1].priority, it[0]))
    known_files = set(ctx.index.get("files", []))
    tasks: list[PlanTask] = []
    for n, (_, t) in enumerate(ordered, start=1):
        file_norm = t.file.replace("\\", "/").lstrip("./")
        tasks.append(
            PlanTask(
                run_id=ctx.run_id,
                task_id=f"TASK-{n:03d}",
                file=file_norm,
                description=t.description,
                reason=t.reason,
                instructions=t.instructions,
                dependencies=t.dependencies,
                expected_changes=t.expected_changes,
                validation=t.validation,
                priority=n,
                status=TaskStatus.PENDING,
            )
        )
        if file_norm not in known_files:
            log.info("plan_targets_new_file", file=file_norm)

    plan = MigrationPlan(
        run_id=ctx.run_id,
        migration=submission.migration,
        overview=submission.overview,
        tasks=tasks,
    )
    await store.save_plan(plan)
    await store.save_checkpoint(
        Checkpoint(
            run_id=ctx.run_id,
            phase=Phase.PLANNING,
            git_sha=ctx.git.current_sha() if ctx.git else None,
            payload={"tasks": len(tasks), "migration": submission.migration},
        )
    )
    await ctx.emit(EventType.CHECKPOINT_CREATED, "Planning checkpoint saved")
    await set_phase_progress(ctx.run_id, Phase.PLANNING, 1.0)
    await ctx.emit(
        EventType.PHASE_COMPLETED,
        f"Plan ready: {len(tasks)} tasks",
        {"phase": "PLANNING", "tasks": [t.task_id for t in tasks]},
    )
