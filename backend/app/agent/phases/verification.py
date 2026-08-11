"""PHASE 5 — VERIFICATION: full suite + syntax sweep + final migration report."""
from __future__ import annotations

import ast
from datetime import timezone

from app.agent.gates import check_gate
from app.agent.progress import set_phase_progress
from app.db.repositories import store
from app.indexing.cloner import IGNORED_DIRS
from app.logging_config import get_logger
from app.models.enums import ApprovalGate, EventType, Phase
from app.models.schemas import Checkpoint, utcnow
from app.tools.registry import ToolContext, ToolError
from app.tools.test_tools import run_tests_impl

log = get_logger("phase.verification")


def _syntax_sweep(ctx: ToolContext) -> list[str]:
    errors = []
    for path in ctx.repo_dir.rglob("*.py"):
        rel = path.relative_to(ctx.repo_dir)
        if any(part in IGNORED_DIRS for part in rel.parts):
            continue
        try:
            ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError as exc:
            errors.append(f"{rel.as_posix()}: line {exc.lineno}: {exc.msg}")
    return errors


async def run(ctx: ToolContext, run) -> None:
    ctx.phase = Phase.VERIFICATION
    await ctx.emit(EventType.PHASE_STARTED, "Verification: final test suite",
                   {"phase": "VERIFICATION"})

    # 1. full suite
    test_status: dict = {}
    try:
        result = await run_tests_impl(ctx, [], attempt=0)
        test_status = result
    except ToolError as exc:
        test_status = {"success": False, "passed": 0, "failed": 0, "errors": 0,
                       "error": str(exc)}
    await set_phase_progress(ctx.run_id, Phase.VERIFICATION, 0.5)

    # 2. syntax sweep across every Python file
    syntax_errors = _syntax_sweep(ctx)

    # 3. dependency sanity (heuristic warning only)
    warnings: list[str] = []
    req = ctx.repo_dir / "requirements.txt"
    if req.is_file():
        req_text = req.read_text(encoding="utf-8", errors="replace").lower()
        source = run.source_tech.lower().strip()
        if source and source in req_text:
            warnings.append(
                f"requirements.txt still mentions '{run.source_tech}' — verify it is intentional"
            )

    # 4. gather stats
    fresh = await store.get_run(ctx.run_id)
    changes = ctx.git.diff_names(fresh.baseline_sha) if fresh.baseline_sha else []
    commits = ctx.git.commits_since(fresh.baseline_sha) if fresh.baseline_sha else 0
    baseline_tests = None
    for rec in await store.list_test_results(ctx.run_id):
        if rec.phase == Phase.INDEXING:
            baseline_tests = {"passed": rec.passed, "failed": rec.failed,
                              "errors": rec.errors}
            break

    duration_s = 0.0
    if fresh.started_at:
        started = fresh.started_at
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        duration_s = round((utcnow() - started).total_seconds(), 1)

    success = bool(test_status.get("success")) and not syntax_errors
    status = "SUCCESS" if success else ("PARTIAL" if test_status.get("passed") else "FAILED")

    report = {
        "migration": f"{run.source_tech} -> {run.target_tech}",
        "goal": run.goal,
        "status": status,
        "files_analyzed": fresh.counters.files_indexed,
        "files_modified": sum(1 for c in changes if c["status"] == "modified"),
        "files_created": sum(1 for c in changes if c["status"] == "added"),
        "files_deleted": sum(1 for c in changes if c["status"] == "deleted"),
        "tests": {
            "passed": test_status.get("passed", 0),
            "failed": test_status.get("failed", 0),
            "errors": test_status.get("errors", 0),
            "duration_s": test_status.get("duration_s", 0),
        },
        "baseline_tests": baseline_tests,
        "repair_attempts": fresh.counters.repair_attempts,
        "git_commits": commits,
        "syntax_errors": syntax_errors,
        "warnings": warnings,
        "duration_s": duration_s,
        "generated_at": utcnow().isoformat(),
    }
    await store.update_run(ctx.run_id, report=report)

    # 5. HITL gate before finalizing
    await check_gate(
        ctx.run_id,
        run.mode,
        ApprovalGate.BEFORE_FINALIZATION,
        "BEFORE_FINALIZATION",
        f"Verification finished with status {status} "
        f"({report['tests']['passed']} passed / {report['tests']['failed']} failed). "
        "Approve to finalize the migration.",
        data={"status": status},
    )

    await store.save_checkpoint(
        Checkpoint(run_id=ctx.run_id, phase=Phase.VERIFICATION,
                   git_sha=ctx.git.current_sha(), payload={"status": status})
    )
    await set_phase_progress(ctx.run_id, Phase.VERIFICATION, 1.0)
    await ctx.emit(
        EventType.PHASE_COMPLETED,
        f"Verification completed: {status}",
        {"phase": "VERIFICATION", "report": {"status": status}},
    )
