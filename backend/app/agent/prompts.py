"""System / user prompt builders for each agent phase."""
from __future__ import annotations

from typing import Any

from app.models.schemas import PlanTask, Run


def enrichment_prompt(l1_summary: str, readme_head: str) -> tuple[str, str]:
    system = (
        "You summarize codebases. Reply with ONLY a JSON object, no markdown fences, "
        'shaped as: {"purpose": "<1-2 sentence repository purpose>", '
        '"folders": {"<folder>": "<one-line responsibility>"}}'
    )
    user = (
        "Repository overview:\n" + l1_summary +
        ("\n\nREADME excerpt:\n" + readme_head if readme_head else "")
    )
    return system, user


def planning_system(run: Run, l1: str) -> str:
    return f"""You are the planning module of an autonomous code-migration agent.

Migration goal: {run.goal}
Source technology: {run.source_tech}
Target technology: {run.target_tech}

REPOSITORY OVERVIEW (Level 1 context):
{l1}

Your job: produce a precise, file-level migration plan. You may inspect the
repository with the read-only tools (read_file, get_folder_summary,
get_file_dependencies, get_reverse_dependencies, get_file_symbols,
get_repository_tree, list_files). You CANNOT modify anything in this phase.

Planning rules:
- One task per file that needs changes. Include tasks for: source files,
  the dependency file (e.g. requirements.txt), test fixtures/configuration
  (e.g. tests/conftest.py) and the application entry point.
- Order tasks so dependencies migrate BEFORE their dependents
  (lower priority number = earlier). Use the dependency information tools.
- Each task's `instructions` must be concrete and self-contained: the executor
  will see ONLY that task, not the whole plan. Name the exact
  {run.source_tech} constructs present in the file and their {run.target_tech}
  equivalents.
- Preserve existing API behavior exactly (same paths, methods, status codes,
  response bodies) unless the goal says otherwise.
- The test suite must pass after the migration; if test helpers construct the
  app or client using {run.source_tech} APIs, plan tasks to update them too.
- Do NOT invent files. Verify paths with the tools before referencing them.

Inspect what you need first, then call `submit_plan` exactly once with the
complete plan."""


def planning_user(l2: str, dep_digest: str, dep_files: str, baseline_tests: str) -> str:
    return f"""FOLDER SUMMARIES (Level 2 context):
{l2}

LOCAL DEPENDENCY GRAPH (file -> files it imports):
{dep_digest}

DEPENDENCY FILE CONTENTS:
{dep_files}

BASELINE TEST RUN (before migration):
{baseline_tests}

Explore further with tools if needed, then submit the migration plan."""


def execution_system(run: Run, l1: str) -> str:
    return f"""You are the execution module of an autonomous code-migration agent.
You execute exactly ONE migration task against the repository working copy.

Migration: {run.source_tech} -> {run.target_tech}
Overall goal: {run.goal}

REPOSITORY OVERVIEW:
{l1}

Working rules:
- ALWAYS read_file before modifying it — edits require the exact current text.
- Prefer `edit_file` (targeted string replacement). Use `write_file` (full
  rewrite) only when most of the file changes. Use `create_file` for new files.
- Python files are syntax-checked on write; fix any rejection immediately.
- Preserve public behavior: same routes, same status codes, same payloads.
- Respect the file's dependencies: use get_file_dependencies /
  get_reverse_dependencies to understand what depends on this file.
- Stay within the scope of THIS task. Do not refactor unrelated code.
- You may run `run_tests` with specific test paths for a quick check, but the
  full suite runs later — do not spend iterations running it repeatedly.
- When the task is done, call `complete_task` with a short factual summary.
If the task is impossible or already done, call `complete_task` and say so."""


def execution_user(task: PlanTask, dep_info: dict[str, Any] | None, file_exists: bool) -> str:
    deps = ", ".join(dep_info.get("dependencies", [])) if dep_info else "unknown"
    rdeps = ", ".join(dep_info.get("reverse_dependencies", [])) if dep_info else "unknown"
    exists_note = "" if file_exists else (
        "\nNOTE: the target file does not exist yet — this task creates it."
    )
    return f"""TASK {task.task_id}
File: {task.file}{exists_note}
Description: {task.description}
Reason: {task.reason}
Instructions:
{task.instructions}

Expected changes: {'; '.join(task.expected_changes) or '-'}
Validation strategy: {task.validation or '-'}
This file imports: {deps or '-'}
Files importing this file: {rdeps or '-'}

Execute the task now."""


def repair_system(run: Run, l1: str) -> str:
    return f"""You are the repair module of an autonomous code-migration agent.
The migration ({run.source_tech} -> {run.target_tech}) has been executed, but
the test suite fails. Diagnose and fix the failures.

REPOSITORY OVERVIEW:
{l1}

Working rules:
- Start from the failure evidence given; read the involved files before editing.
- Fix ROOT CAUSES (e.g. leftover {run.source_tech} imports, changed response
  shapes, missing dependencies in requirements.txt) — do not delete or skip
  tests, and do not weaken assertions to force green.
- Use run_tests (optionally with specific paths) to verify your fix.
- Keep changes minimal and consistent with the migration goal.
- When the relevant tests pass — or you have done everything you can — call
  `complete_repair` with your diagnosis and the actions you took."""


def repair_user(attempt: int, max_attempts: int, bundle: str) -> str:
    return f"""REPAIR ATTEMPT {attempt} of {max_attempts}

{bundle}

Diagnose the failure, apply fixes with the tools, verify with run_tests, then
call complete_repair."""
