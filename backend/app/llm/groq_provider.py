"""Groq provider — OpenAI-compatible chat completions API via httpx."""
from __future__ import annotations

import json
from typing import Any

import httpx

from app.config import settings
from app.llm.base import (
    AuthError,
    LLMMessage,
    LLMProvider,
    LLMResponse,
    MalformedResponseError,
    QuotaExhaustedError,
    RateLimitError,
    ToolCall,
    TransientError,
    sanitize_schema,
)
from app.logging_config import get_logger

log = get_logger("llm.groq")

API_URL = "https://api.groq.com/openai/v1/chat/completions"


class GroqProvider(LLMProvider):
    name = "groq"

    def __init__(self, api_key: str, model: str | None = None):
        if not api_key:
            raise AuthError("GROQ_API_KEY is not set")
        self.api_key = api_key
        self.model = model or settings.groq_model
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(180.0, connect=15.0))

    def _convert_messages(self, messages: list[LLMMessage]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for m in messages:
            if m.role == "tool":
                out.append(
                    {"role": "tool", "tool_call_id": m.tool_call_id or "", "content": m.content}
                )
            elif m.role == "assistant" and m.tool_calls:
                out.append(
                    {
                        "role": "assistant",
                        "content": m.content or None,
                        "tool_calls": [
                            {
                                "id": tc.id,
                                "type": "function",
                                "function": {
                                    "name": tc.name,
                                    "arguments": json.dumps(tc.arguments),
                                },
                            }
                            for tc in m.tool_calls
                        ],
                    }
                )
            else:
                out.append({"role": m.role, "content": m.content})
        return out

    async def complete(
        self,
        messages: list[LLMMessage],
        tools: list[dict[str, Any]] | None = None,
        force_tool: str | None = None,
    ) -> LLMResponse:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": self._convert_messages(messages),
            "temperature": settings.llm_temperature,
            "max_tokens": settings.llm_max_output_tokens,
        }
        if tools:
            body["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t["name"],
                        "description": t["description"],
                        "parameters": sanitize_schema(t["parameters"]),
                    },
                }
                for t in tools
            ]
            body["tool_choice"] = (
                {"type": "function", "function": {"name": force_tool}}
                if force_tool
                else "auto"
            )

        try:
            resp = await self._client.post(
                API_URL,
                json=body,
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
        except httpx.HTTPError as exc:
            raise TransientError(f"Groq network error: {exc}") from exc

        if resp.status_code == 401:
            raise AuthError("Groq rejected the API key (401)")
        if resp.status_code == 429:
            retry_after = None
            if resp.headers.get("retry-after"):
                try:
                    retry_after = float(resp.headers["retry-after"])
                except ValueError:
                    retry_after = None
            text = resp.text[:500]
            if "quota" in text.lower() or "billing" in text.lower():
                raise QuotaExhaustedError(f"Groq quota exhausted: {text}")
            raise RateLimitError(f"Groq rate limited: {text}", retry_after=retry_after)
        if resp.status_code >= 500:
            raise TransientError(f"Groq server error {resp.status_code}: {resp.text[:300]}")
        if resp.status_code >= 400:
            raise MalformedResponseError(
                f"Groq request failed ({resp.status_code}): {resp.text[:1000]}"
            )

        data = resp.json()
        try:
            choice = data["choices"][0]["message"]
        except (KeyError, IndexError) as exc:
            raise MalformedResponseError(f"Unexpected Groq response: {data}") from exc

        tool_calls: list[ToolCall] = []
        for tc in choice.get("tool_calls") or []:
            try:
                args = json.loads(tc["function"].get("arguments") or "{}")
                if not isinstance(args, dict):
                    args = {}
            except json.JSONDecodeError:
                args = {"__malformed_json__": tc["function"].get("arguments", "")[:2000]}
            tool_calls.append(
                ToolCall(id=tc.get("id", ""), name=tc["function"]["name"], arguments=args)
            )

        usage = data.get("usage") or {}
        return LLMResponse(
            text=choice.get("content") or "",
            tool_calls=tool_calls,
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            raw=data,
        )
