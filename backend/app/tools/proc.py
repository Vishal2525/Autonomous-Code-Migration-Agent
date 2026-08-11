"""Shared subprocess runner with timeout + captured output."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ProcResult:
    exit_code: int | None
    stdout: str
    stderr: str
    timed_out: bool = False

    def tail(self, n: int = 6000) -> str:
        combined = (self.stdout or "") + ("\n" + self.stderr if self.stderr else "")
        return combined[-n:]


async def run_process(
    cmd: list[str], cwd: Path, timeout: int, env: dict | None = None
) -> ProcResult:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    try:
        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        try:
            stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=10)
        except asyncio.TimeoutError:
            stdout_b, stderr_b = b"", b""
        return ProcResult(
            exit_code=None,
            stdout=stdout_b.decode(errors="replace"),
            stderr=stderr_b.decode(errors="replace"),
            timed_out=True,
        )
    return ProcResult(
        exit_code=proc.returncode,
        stdout=stdout_b.decode(errors="replace"),
        stderr=stderr_b.decode(errors="replace"),
    )
