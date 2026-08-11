"""Tool layer core: every agent action goes through a registered, schema-validated tool.

Guarantees per tool call:
- strict Pydantic input validation
- timeout enforcement
- structured ToolResult (errors are returned to the LLM, never crash the loop)
- mutation gating (read-only phases cannot call mutating tools)
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

from pydantic import BaseModel, ValidationError

from app.config import settings
from app.gitops.manager import GitManager
from app.logging_config import get_logger
from app.models.enums import ApprovalGate, Phase, RunMode

log = get_logger("tools")


class ToolError(Exception):
    """Expected tool failure — message is returned to the LLM."""


class ApprovalRequiredError(Exception):
    """Raised when a tool needs human approval before it may proceed.

    Bubbles out of the agent loop; the orchestrator parks the run in
    WAITING_FOR_APPROVAL and the task re-runs after approval.
    """

    def __init__(self, gate: ApprovalGate, key: str, detail: str, data: dict | None = None):
        self.gate = gate
        self.key = key
        self.detail = detail
        self.data = data or {}
        super().__init__(detail)


@dataclass
class ToolContext:
    """Everything a tool handler may touch. One instance per run (worker)."""

    run_id: str
    repo_dir: Path
    workspace_dir: Path
    mode: RunMode
    phase: Phase
    store: Any  # app.db.repositories.Store
    git: GitManager
    emit: Callable[..., Awaitable[None]]  # event_bus emit bound to run_id
    index: dict[str, Any] = field(default_factory=dict)  # repository index doc
    approved_keys: set[str] = field(default_factory=set)  # granted approval keys
    venv_python: Path | None = None
    touched_files: set[str] = field(default_factory=set)  # files changed this task


@dataclass
class Tool:
    name: str
    description: str
    input_model: type[BaseModel]
    handler: Callable[[ToolContext, BaseModel], Awaitable[Any]]
    mutating: bool = False
    timeout: int | None = None  # seconds; defaults to settings.tool_timeout


@dataclass
class ToolResult:
    ok: bool
    data: Any = None
    error: str | None = None

    def for_llm(self, max_chars: int = 24000) -> str:
        if self.ok:
            payload = self.data if self.data is not None else "OK"
            text = payload if isinstance(payload, str) else json.dumps(payload, default=str)
        else:
            text = json.dumps({"error": self.error})
        if len(text) > max_chars:
            text = text[:max_chars] + f"\n... (truncated at {max_chars} chars)"
        return text


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Duplicate tool: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def specs(self, include_mutating: bool = True) -> list[dict[str, Any]]:
        """Neutral tool specs [{name, description, parameters}] for the LLM layer."""
        specs = []
        for tool in self._tools.values():
            if tool.mutating and not include_mutating:
                continue
            schema = tool.input_model.model_json_schema()
            specs.append(
                {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": schema,
                }
            )
        return specs

    async def execute(
        self, ctx: ToolContext, name: str, raw_args: dict[str, Any], allow_mutations: bool
    ) -> ToolResult:
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult(ok=False, error=f"Unknown tool: {name}")
        if tool.mutating and not allow_mutations:
            return ToolResult(
                ok=False,
                error=f"Tool '{name}' modifies the repository and is not allowed "
                f"in the {ctx.phase.value} phase (read-only).",
            )
        try:
            args = tool.input_model(**(raw_args or {}))
        except ValidationError as exc:
            return ToolResult(ok=False, error=f"Invalid arguments for {name}: {exc}")

        timeout = tool.timeout or settings.tool_timeout
        try:
            data = await asyncio.wait_for(tool.handler(ctx, args), timeout=timeout)
            return ToolResult(ok=True, data=data)
        except ApprovalRequiredError:
            raise  # handled by the orchestrator, not returned to the LLM
        except asyncio.TimeoutError:
            return ToolResult(ok=False, error=f"Tool '{name}' timed out after {timeout}s")
        except ToolError as exc:
            return ToolResult(ok=False, error=str(exc))
        except Exception as exc:  # defensive: tool bugs must not kill the agent
            log.error("tool_crashed", tool=name, error=repr(exc))
            return ToolResult(ok=False, error=f"Tool '{name}' crashed: {exc!r}")
