"""Google Gemini provider — generateContent REST API with function calling."""

from __future__ import annotations

import re
import uuid
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


log = get_logger("llm.gemini")

BASE_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models"
)


class GeminiProvider(LLMProvider):
    name = "gemini"

    def __init__(
        self,
        api_key: str,
        model: str | None = None,
    ):
        if not api_key:
            raise AuthError("GEMINI_API_KEY is not set")

        self.api_key = api_key

        # Normalize model name.
        #
        # Accepts both:
        #   gemini-3.5-flash
        #   models/gemini-3.5-flash
        #
        # Internally we always store:
        #   gemini-3.5-flash
        self.model = (
            model or settings.gemini_model
        ).removeprefix("models/")

        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(
                180.0,
                connect=15.0,
            )
        )

        log.info(
            "Gemini provider initialized with model=%s",
            self.model,
        )

    def _convert(
        self,
        messages: list[LLMMessage],
    ) -> tuple[str, list[dict[str, Any]]]:
        """
        Split system text out and convert the remaining
        messages to Gemini `contents`.
        """

        system_parts: list[str] = []
        contents: list[dict[str, Any]] = []

        for m in messages:
            # -----------------------------
            # System message
            # -----------------------------
            if m.role == "system":
                if m.content:
                    system_parts.append(m.content)

            # -----------------------------
            # User message
            # -----------------------------
            elif m.role == "user":
                if m.content:
                    contents.append(
                        {
                            "role": "user",
                            "parts": [
                                {
                                    "text": m.content,
                                }
                            ],
                        }
                    )

            # -----------------------------
            # Assistant / model message
            # -----------------------------
            elif m.role == "assistant":
                parts: list[dict[str, Any]] = []

                if m.content:
                    parts.append(
                        {
                            "text": m.content,
                        }
                    )

                for tc in m.tool_calls:
                    parts.append(
                        {
                            "functionCall": {
                                "name": tc.name,
                                "args": tc.arguments,
                            }
                        }
                    )

                if parts:
                    contents.append(
                        {
                            "role": "model",
                            "parts": parts,
                        }
                    )

            # -----------------------------
            # Tool response
            # -----------------------------
            elif m.role == "tool":
                contents.append(
                    {
                        "role": "user",
                        "parts": [
                            {
                                "functionResponse": {
                                    "name": m.name or "tool",
                                    "response": {
                                        "result": m.content,
                                    },
                                }
                            }
                        ],
                    }
                )

        return "\n\n".join(system_parts), contents

    async def complete(
        self,
        messages: list[LLMMessage],
        tools: list[dict[str, Any]] | None = None,
        force_tool: str | None = None,
    ) -> LLMResponse:
        """
        Send a completion request to Gemini using the
        generateContent REST API.
        """

        system_text, contents = self._convert(messages)

        # Gemini 3.x models should not blindly receive
        # older temperature/top_p/top_k settings.
        body: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "maxOutputTokens": settings.llm_max_output_tokens,
            },
        }

        # -----------------------------
        # System instruction
        # -----------------------------
        if system_text:
            body["systemInstruction"] = {
                "parts": [
                    {
                        "text": system_text,
                    }
                ]
            }

        # -----------------------------
        # Function calling / tools
        # -----------------------------
        if tools:
            body["tools"] = [
                {
                    "functionDeclarations": [
                        {
                            "name": t["name"],
                            "description": t["description"],
                            "parameters": sanitize_schema(
                                t["parameters"],
                                for_gemini=True,
                            ),
                        }
                        for t in tools
                    ]
                }
            ]

            # Force a specific tool when requested.
            if force_tool:
                body["toolConfig"] = {
                    "functionCallingConfig": {
                        "mode": "ANY",
                        "allowedFunctionNames": [
                            force_tool
                        ],
                    }
                }

        # -----------------------------
        # Gemini REST endpoint
        # -----------------------------
        url = (
            f"{BASE_URL}/"
            f"{self.model}:generateContent"
        )

        log.debug(
            "Calling Gemini model=%s",
            self.model,
        )

        try:
            resp = await self._client.post(
                url,
                json=body,
                headers={
                    "x-goog-api-key": self.api_key,
                    "Content-Type": "application/json",
                },
            )

        except httpx.HTTPError as exc:
            raise TransientError(
                f"Gemini network error: {exc}"
            ) from exc

        # -----------------------------
        # Authentication errors
        # -----------------------------
        if resp.status_code in (401, 403):
            raise AuthError(
                "Gemini rejected the API key "
                f"({resp.status_code})"
            )

        # -----------------------------
        # Rate limit / quota
        # -----------------------------
        if resp.status_code == 429:
            text = resp.text[:800]
            retry_after = _extract_retry_delay(text)

            quota_markers = (
                "quota",
                "QuotaFailure",
                "exceeded your current quota",
                "RESOURCE_EXHAUSTED",
            )

            if any(marker in text for marker in quota_markers):
                raise QuotaExhaustedError(
                    f"Gemini quota exhausted: {text[:500]}"
                )

            raise RateLimitError(
                f"Gemini rate limited: {text[:500]}",
                retry_after=retry_after,
            )

        # -----------------------------
        # Server errors
        # -----------------------------
        if resp.status_code >= 500:
            raise TransientError(
                "Gemini server error "
                f"{resp.status_code}: "
                f"{resp.text[:300]}"
            )

        # -----------------------------
        # Other client errors
        # -----------------------------
        if resp.status_code >= 400:
            raise MalformedResponseError(
                "Gemini request failed "
                f"({resp.status_code}): "
                f"{resp.text[:1000]}"
            )

        # -----------------------------
        # Parse JSON response
        # -----------------------------
        try:
            data = resp.json()
        except ValueError as exc:
            raise MalformedResponseError(
                "Gemini returned invalid JSON: "
                f"{resp.text[:1000]}"
            ) from exc

        # -----------------------------
        # Candidates
        # -----------------------------
        candidates = data.get("candidates") or []

        if not candidates:
            feedback = data.get(
                "promptFeedback",
                {},
            )

            raise MalformedResponseError(
                "Gemini returned no candidates: "
                f"{feedback}"
            )

        candidate = candidates[0]

        content = candidate.get("content") or {}
        parts = content.get("parts") or []

        # -----------------------------
        # Extract text
        # -----------------------------
        text_out = "".join(
            p.get("text", "")
            for p in parts
            if "text" in p
        )

        # -----------------------------
        # Extract function calls
        # -----------------------------
        tool_calls: list[ToolCall] = []

        for p in parts:
            if "functionCall" not in p:
                continue

            function_call = p["functionCall"]

            tool_calls.append(
                ToolCall(
                    id=(
                        f"call_"
                        f"{uuid.uuid4().hex[:10]}"
                    ),
                    name=function_call.get(
                        "name",
                        "",
                    ),
                    arguments=function_call.get(
                        "args"
                    )
                    or {},
                )
            )

        # -----------------------------
        # Usage metadata
        # -----------------------------
        usage = data.get(
            "usageMetadata"
        ) or {}

        prompt_tokens = usage.get(
            "promptTokenCount",
            0,
        )

        completion_tokens = usage.get(
            "candidatesTokenCount",
            0,
        )

        return LLMResponse(
            text=text_out,
            tool_calls=tool_calls,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            raw=data,
        )

    async def close(self) -> None:
        """Close the underlying HTTP client."""

        await self._client.aclose()


def _extract_retry_delay(
    error_text: str,
) -> float | None:
    """
    Gemini 429 responses often contain:

        "retryDelay": "22s"

    Return the delay in seconds when available.
    """

    match = re.search(
        r'"retryDelay"\s*:\s*"'
        r'(\d+(?:\.\d+)?)s"',
        error_text,
    )

    return (
        float(match.group(1))
        if match
        else None
    )