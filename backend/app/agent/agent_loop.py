"""The generic LLM ↔ tool loop.

    LLM → tool call → tool result → LLM → ... until the finish tool is called
    (or the iteration cap is hit).

Transcripts are per-invocation (per task), which is what keeps context bounded
on long runs. Old tool results are additionally trimmed once the transcript
grows past a window.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ValidationError

from app.agent.control import check_control
from app.config import settings
from app.llm.base import LLMMessage, sanitize_schema
from app.llm.resilience import ResilientLLM
from app.logging_config import get_logger
from app.tools.registry import ToolContext, ToolRegistry

log = get_logger("agent.loop")

#: keep the system + first user message, plus this many recent messages
TRANSCRIPT_WINDOW = 40


@dataclass
class FinishTool:
    name: str
    description: str
    input_model: type[BaseModel]


@dataclass
class LoopResult:
    finished: bool
    finish_args: dict[str, Any] | None = None
    text: str = ""
    iterations: int = 0
    tool_calls_made: int = 0
    errors: list[str] = field(default_factory=list)


def _trim_transcript(messages: list[LLMMessage]) -> list[LLMMessage]:
    if len(messages) <= TRANSCRIPT_WINDOW + 2:
        return messages
    head = messages[:2]  # system + initial user prompt
    tail = messages[-TRANSCRIPT_WINDOW:]
    # never let the window start with an orphan tool result (breaks provider APIs)
    while tail and tail[0].role == "tool":
        tail = tail[1:]
    note = LLMMessage(
        role="user",
        content="[Earlier tool interactions trimmed to save context. "
        "Re-read files if you need their content again.]",
    )
    return head + [note] + tail


async def run_agent_loop(
    ctx: ToolContext,
    llm: ResilientLLM,
    registry: ToolRegistry,
    system_prompt: str,
    user_prompt: str,
    *,
    allow_mutations: bool,
    finish_tool: FinishTool,
    max_iterations: int | None = None,
) -> LoopResult:
    max_iter = max_iterations or settings.max_agent_iterations
    specs = registry.specs(include_mutating=allow_mutations)
    specs.append(
        {
            "name": finish_tool.name,
            "description": finish_tool.description,
            "parameters": sanitize_schema(finish_tool.input_model.model_json_schema()),
        }
    )

    messages: list[LLMMessage] = [
        LLMMessage(role="system", content=system_prompt),
        LLMMessage(role="user", content=user_prompt),
    ]
    result = LoopResult(finished=False)
    nudges = 0

    for iteration in range(1, max_iter + 1):
        result.iterations = iteration
        await check_control(ctx.run_id)
        # force the finish tool on the final iteration so the loop always concludes
        force = finish_tool.name if iteration == max_iter else None
        response = await llm.complete(_trim_transcript(messages), tools=specs, force_tool=force)

        if not response.tool_calls:
            result.text = response.text
            nudges += 1
            if nudges > 2:
                result.errors.append("Model stopped calling tools before finishing")
                return result
            messages.append(LLMMessage(role="assistant", content=response.text))
            messages.append(
                LLMMessage(
                    role="user",
                    content=f"Continue using tools, or call `{finish_tool.name}` "
                    "if the work is done.",
                )
            )
            continue

        messages.append(
            LLMMessage(role="assistant", content=response.text, tool_calls=response.tool_calls)
        )

        for tc in response.tool_calls:
            if tc.name == finish_tool.name:
                try:
                    validated = finish_tool.input_model(**tc.arguments)
                except ValidationError as exc:
                    messages.append(
                        LLMMessage(
                            role="tool",
                            tool_call_id=tc.id,
                            name=tc.name,
                            content=f'{{"error": "Invalid {finish_tool.name} arguments: {exc}"}}',
                        )
                    )
                    continue
                result.finished = True
                result.finish_args = validated.model_dump()
                result.text = response.text
                return result

            tool_result = await registry.execute(ctx, tc.name, tc.arguments, allow_mutations)
            result.tool_calls_made += 1
            if not tool_result.ok:
                result.errors.append(f"{tc.name}: {tool_result.error}")
            messages.append(
                LLMMessage(
                    role="tool",
                    tool_call_id=tc.id,
                    name=tc.name,
                    content=tool_result.for_llm(),
                )
            )

    result.errors.append(f"Iteration cap ({max_iter}) reached without {finish_tool.name}")
    return result
