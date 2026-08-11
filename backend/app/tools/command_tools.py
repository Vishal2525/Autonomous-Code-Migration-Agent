"""Restricted command execution — allowlisted commands only, never arbitrary shell."""
from __future__ import annotations

from pydantic import BaseModel, Field

from app.config import settings
from app.tools.proc import run_process
from app.tools.registry import Tool, ToolContext, ToolError, ToolRegistry
from app.tools.test_tools import ensure_venv

ALLOWED_PIP_SUBCOMMANDS = {"install", "uninstall", "list", "show", "freeze"}


class RunCommandArgs(BaseModel):
    command: str = Field(description="One of: pip, pytest, python")
    args: list[str] = Field(default_factory=list, description="Arguments for the command")


async def run_command(ctx: ToolContext, args: RunCommandArgs):
    python = await ensure_venv(ctx)
    command = args.command.strip().lower()

    for a in args.args:
        if not isinstance(a, str) or len(a) > 2000:
            raise ToolError("Invalid argument")

    if command == "pip":
        if not args.args or args.args[0] not in ALLOWED_PIP_SUBCOMMANDS:
            raise ToolError(
                f"pip subcommand must be one of {sorted(ALLOWED_PIP_SUBCOMMANDS)}"
            )
        if args.args[0] == "uninstall" and "-y" not in args.args:
            args.args = [args.args[0], "-y", *args.args[1:]]
        cmd = [str(python), "-m", "pip", "--disable-pip-version-check", *args.args]
        timeout = settings.pip_timeout
    elif command == "pytest":
        cmd = [str(python), "-m", "pytest", "-p", "no:cacheprovider", *args.args]
        timeout = settings.test_timeout
    elif command == "python":
        cmd = [str(python), *args.args]
        timeout = settings.test_timeout
    else:
        raise ToolError("Command not allowed. Allowed commands: pip, pytest, python")

    result = await run_process(cmd, cwd=ctx.repo_dir, timeout=timeout)
    return {
        "exit_code": result.exit_code,
        "timed_out": result.timed_out,
        "output": result.tail(12000),
    }


def register_command_tools(registry: ToolRegistry) -> None:
    registry.register(Tool(
        name="run_command",
        description="Run an allowlisted command (pip / pytest / python) inside the run's "
                    "virtualenv with the repository as working directory. "
                    "Example: {'command': 'pip', 'args': ['install', '-r', 'requirements.txt']}",
        input_model=RunCommandArgs,
        handler=run_command,
        mutating=True,  # pip install changes the environment
        timeout=settings.pip_timeout + settings.test_timeout + 60,
    ))
