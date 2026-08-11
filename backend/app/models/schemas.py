"""Pydantic models shared by the API, the agent, and MongoDB persistence."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from app.models.enums import (
    ApprovalGate,
    EventType,
    Phase,
    RunMode,
    RunState,
    TaskStatus,
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RunCreate(BaseModel):
    repository_url: str = Field(min_length=3)
    goal: str = Field(min_length=3)
    source_tech: str = Field(min_length=1)
    target_tech: str = Field(min_length=1)
    mode: RunMode = RunMode.AUTO


class LLMUsage(BaseModel):
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class RunCounters(BaseModel):
    files_indexed: int = 0
    files_processed: int = 0
    files_modified: int = 0
    files_created: int = 0
    files_deleted: int = 0
    tests_passed: int = 0
    tests_failed: int = 0
    repair_attempts: int = 0
    git_commits: int = 0


class Run(BaseModel):
    run_id: str
    repository_url: str
    goal: str
    source_tech: str
    target_tech: str
    mode: RunMode = RunMode.AUTO
    status: RunState = RunState.CREATED
    phase: Phase | None = None
    current_task_id: str | None = None
    current_file: str | None = None
    workspace: str | None = None
    repo_dir: str | None = None
    baseline_sha: str | None = None
    head_sha: str | None = None
    progress: float = 0.0
    counters: RunCounters = Field(default_factory=RunCounters)
    llm_usage: LLMUsage = Field(default_factory=LLMUsage)
    error: str | None = None
    pause_requested: bool = False
    cancel_requested: bool = False
    report: dict[str, Any] | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    started_at: datetime | None = None
    finished_at: datetime | None = None


class PlanTask(BaseModel):
    run_id: str
    task_id: str
    file: str
    description: str
    reason: str = ""
    instructions: str = ""
    dependencies: list[str] = Field(default_factory=list)
    expected_changes: list[str] = Field(default_factory=list)
    validation: str = ""
    priority: int = 100
    status: TaskStatus = TaskStatus.PENDING
    result_summary: str | None = None
    git_sha: str | None = None
    error: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class MigrationPlan(BaseModel):
    run_id: str
    migration: str
    overview: str = ""
    tasks: list[PlanTask] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utcnow)


class Checkpoint(BaseModel):
    run_id: str
    phase: Phase
    task_id: str | None = None
    status: str = "completed"  # completed | failed
    git_sha: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utcnow)


class Event(BaseModel):
    run_id: str
    event: EventType
    message: str = ""
    data: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utcnow)


class TestRunRecord(BaseModel):
    run_id: str
    phase: Phase
    attempt: int = 0
    exit_code: int | None = None
    passed: int = 0
    failed: int = 0
    errors: int = 0
    skipped: int = 0
    duration_s: float = 0.0
    failing_tests: list[str] = Field(default_factory=list)
    output_tail: str = ""
    timed_out: bool = False
    created_at: datetime = Field(default_factory=utcnow)


class Approval(BaseModel):
    run_id: str
    gate: ApprovalGate
    key: str  # unique per gate instance, e.g. "AFTER_PLANNING" or "DESTRUCTIVE:TASK-004"
    detail: str = ""
    data: dict[str, Any] = Field(default_factory=dict)
    status: str = "pending"  # pending | approved | rejected
    created_at: datetime = Field(default_factory=utcnow)
    resolved_at: datetime | None = None
