"""Provider-neutral LLM abstraction.

The rest of the application only ever sees LLMMessage / LLMResponse / ToolCall.
Gemini and Groq adapters translate to and from their wire formats.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


class LLMError(Exception):
    """Base class for LLM failures."""


class RateLimitError(LLMError):
    def __init__(self, message: str, retry_after: float | None = None):
        super().__init__(message)
        self.retry_after = retry_after


class TransientError(LLMError):
    """5xx / network problems — safe to retry."""


class AuthError(LLMError):
    """Invalid or missing API key — fatal, do not retry."""


class QuotaExhaustedError(LLMError):
    """Hard quota exhaustion — fatal for this run, do not spin."""


class MalformedResponseError(LLMError):
    """Provider returned something we cannot interpret."""


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass
class LLMMessage:
    role: str  # system | user | assistant | tool
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str | None = None  # for role="tool"
    name: str | None = None  # tool name for role="tool"


@dataclass
class LLMResponse:
    text: str
    tool_calls: list[ToolCall]
    prompt_tokens: int = 0
    completion_tokens: int = 0
    raw: Any = None


class LLMProvider(ABC):
    name: str = "base"
    model: str = ""

    @abstractmethod
    async def complete(
        self,
        messages: list[LLMMessage],
        tools: list[dict[str, Any]] | None = None,
        force_tool: str | None = None,
    ) -> LLMResponse:
        """One chat completion. `tools` are neutral specs {name, description, parameters}.

        `force_tool` requires the model to call that specific tool.
        """


def _inline_refs(schema: Any, defs: dict[str, Any], depth: int = 0) -> Any:
    """Resolve '#/$defs/X' references so providers get self-contained schemas."""
    if depth > 12:
        return schema
    if isinstance(schema, list):
        return [_inline_refs(s, defs, depth + 1) for s in schema]
    if not isinstance(schema, dict):
        return schema
    if "$ref" in schema:
        name = str(schema["$ref"]).split("/")[-1]
        target = defs.get(name, {})
        merged = {**target, **{k: v for k, v in schema.items() if k != "$ref"}}
        return _inline_refs(merged, defs, depth + 1)
    return {k: _inline_refs(v, defs, depth + 1) for k, v in schema.items()}


def sanitize_schema(schema: Any, *, for_gemini: bool = False) -> Any:
    """Clean Pydantic-generated JSON schemas for provider consumption.

    - inlines $defs/$ref (nested models) into self-contained schemas
    - drops noise keys (title, default)
    - for Gemini: collapses `anyOf [X, null]` into X with nullable=true
    """
    if isinstance(schema, dict) and ("$defs" in schema or "definitions" in schema):
        defs = {**schema.get("$defs", {}), **schema.get("definitions", {})}
        schema = _inline_refs(
            {k: v for k, v in schema.items() if k not in ("$defs", "definitions")}, defs
        )
    if isinstance(schema, list):
        return [sanitize_schema(s, for_gemini=for_gemini) for s in schema]
    if not isinstance(schema, dict):
        return schema

    schema = {
        k: v for k, v in schema.items()
        if k not in ("title", "default", "$defs", "definitions", "additionalProperties")
    }

    if "anyOf" in schema:
        options = [o for o in schema["anyOf"] if o.get("type") != "null"]
        nullable = len(options) < len(schema["anyOf"])
        if len(options) == 1:
            merged = {**schema, **options[0]}
            merged.pop("anyOf", None)
            schema = merged
            if for_gemini and nullable:
                schema["nullable"] = True
        elif for_gemini:
            # Gemini dislikes generic anyOf — fall back to string
            schema.pop("anyOf")
            schema.setdefault("type", "string")

    return {k: sanitize_schema(v, for_gemini=for_gemini) for k, v in schema.items()}
