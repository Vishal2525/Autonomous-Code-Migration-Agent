"""Test execution in a per-run virtualenv, with parsed structured results."""
from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from app.config import settings
from app.logging_config import get_logger
from app.models.enums import EventType
from app.models.schemas import TestRunRecord
from app.tools.proc import run_process
from app.tools.registry import Tool, ToolContext, ToolError, ToolRegistry

log = get_logger("tools.tests")

_SUMMARY_PATTERNS = {
    "passed": re.compile(r"(\d+) passed"),
    "failed": re.compile(r"(\d+) failed"),
    "errors": re.compile(r"(\d+) error"),
    "skipped": re.compile(r"(\d+) skipped"),
}
_DURATION = re.compile(r"in ([\d.]+)s")
_FAILED_LINE = re.compile(r"^(?:FAILED|ERROR) ([^\s]+)", re.MULTILINE)


def venv_python_path(workspace_dir: Path) -> Path:
    sub = "Scripts/python.exe" if sys.platform == "win32" else "bin/python"
    return workspace_dir / "venv" / sub


async def ensure_venv(ctx: ToolContext) -> Path:
    """Create the run venv and (re)install repo requirements when they change."""
    python = venv_python_path(ctx.workspace_dir)
    venv_dir = ctx.workspace_dir / "venv"
    if not python.exists():
        log.info("creating_venv", dir=str(venv_dir))
        result = await run_process(
            [sys.executable, "-m", "venv", str(venv_dir)],
            cwd=ctx.workspace_dir, timeout=180,
        )
        if result.exit_code != 0:
            raise ToolError(f"venv creation failed: {result.tail(2000)}")

    req_file = ctx.repo_dir / "requirements.txt"
    req_hash = (
        hashlib.sha1(req_file.read_bytes()).hexdigest() if req_file.is_file() else "none"
    )
    stamp = venv_dir / ".requirements.sha1"
    if not stamp.exists() or stamp.read_text().strip() != req_hash:
        cmd = [str(python), "-m", "pip", "install", "--disable-pip-version-check", "pytest"]
        if req_file.is_file():
            cmd += ["-r", str(req_file)]
        log.info("installing_requirements", changed=True)
        result = await run_process(cmd, cwd=ctx.repo_dir, timeout=settings.pip_timeout)
        if result.exit_code != 0:
            raise ToolError(
                "Dependency installation failed:\n" + result.tail(4000)
            )
        stamp.write_text(req_hash)
    ctx.venv_python = python
    return python


def parse_pytest_output(output: str) -> dict[str, Any]:
    counts = {
        key: int(m.group(1)) if (m := pat.search(output)) else 0
        for key, pat in _SUMMARY_PATTERNS.items()
    }
    duration = float(m.group(1)) if (m := _DURATION.search(output)) else 0.0
    failing = _FAILED_LINE.findall(output)
    return {**counts, "duration_s": duration, "failing_tests": failing[:50]}


class RunTestsArgs(BaseModel):
    paths: list[str] = Field(
        default_factory=list,
        description="Optional test files/folders to run (repo-relative). Empty = full suite.",
    )
    keyword: str | None = Field(
        default=None, description="Optional pytest -k expression to filter tests"
    )


async def run_tests_impl(ctx: ToolContext, paths: list[str], keyword: str | None = None,
                         attempt: int = 0) -> dict[str, Any]:
    python = await ensure_venv(ctx)
    cmd = [str(python), "-m", "pytest", "-q", "--tb=short", "-p", "no:cacheprovider"]
    for p in paths:
        if ".." in p or Path(p).is_absolute():
            raise ToolError(f"Invalid test path: {p}")
        cmd.append(p)
    if keyword:
        cmd += ["-k", keyword]

    await ctx.emit(EventType.TEST_STARTED, f"Running tests: {' '.join(paths) or 'full suite'}")
    result = await run_process(cmd, cwd=ctx.repo_dir, timeout=settings.test_timeout)
    output = result.tail(20000)
    parsed = parse_pytest_output(output)
    ok = result.exit_code == 0 and not result.timed_out

    record = TestRunRecord(
        run_id=ctx.run_id,
        phase=ctx.phase,
        attempt=attempt,
        exit_code=result.exit_code,
        passed=parsed["passed"],
        failed=parsed["failed"],
        errors=parsed["errors"],
        skipped=parsed["skipped"],
        duration_s=parsed["duration_s"],
        failing_tests=parsed["failing_tests"],
        output_tail=output[-8000:],
        timed_out=result.timed_out,
    )
    await ctx.store.add_test_result(record)
    await ctx.store.update_run(
        ctx.run_id,
        **{
            "counters.tests_passed": parsed["passed"],
            "counters.tests_failed": parsed["failed"] + parsed["errors"],
        },
    )
    if ok:
        await ctx.emit(
            EventType.TEST_PASSED,
            f"Tests passed: {parsed['passed']} passed in {parsed['duration_s']}s",
            {"passed": parsed["passed"]},
        )
    else:
        await ctx.emit(
            EventType.TEST_FAILED,
            f"Tests failed: {parsed['failed']} failed, {parsed['errors']} errors "
            f"({'timeout' if result.timed_out else f'exit {result.exit_code}'})",
            {"failing_tests": parsed["failing_tests"]},
        )
    return {
        "success": ok,
        "exit_code": result.exit_code,
        "timed_out": result.timed_out,
        **parsed,
        "output": output[-12000:],
    }


async def run_tests(ctx: ToolContext, args: RunTestsArgs):
    return await run_tests_impl(ctx, args.paths, args.keyword)


def register_test_tools(registry: ToolRegistry) -> None:
    registry.register(Tool(
        name="run_tests",
        description="Run pytest inside the run's virtualenv. Returns pass/fail counts, "
                    "failing test ids and the output tail. Dependencies from "
                    "requirements.txt are (re)installed automatically when the file changes.",
        input_model=RunTestsArgs,
        handler=run_tests,
        timeout=settings.pip_timeout + settings.test_timeout + 60,
    ))
