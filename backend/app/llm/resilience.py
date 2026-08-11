"""Retry / fallback wrapper around any LLMProvider + usage accounting."""

from __future__ import annotations

import asyncio
import random
from typing import Any, Awaitable, Callable

from app.config import settings
from app.llm.base import (
    AuthError,
    LLMMessage,
    LLMProvider,
    LLMResponse,
    MalformedResponseError,
    QuotaExhaustedError,
    RateLimitError,
    TransientError,
)
from app.logging_config import get_logger


log = get_logger("llm.resilience")


UsageCallback = Callable[[int, int], Awaitable[None]]


class ResilientLLM:
    """
    Retry / fallback wrapper around LLM providers.

    Behavior:

        Primary provider
            |
            +-- Success --------------------> return response
            |
            +-- RateLimitError ------------> retry with backoff
            |
            +-- TransientError ------------> retry with backoff
            |
            +-- MalformedResponseError ----> retry once
            |
            +-- QuotaExhaustedError -------> switch provider
            |
            +-- AuthError -----------------> fail immediately

        If the primary provider cannot recover,
        the fallback provider is attempted.
    """

    def __init__(
        self,
        provider: LLMProvider,
        fallback_provider: LLMProvider | None = None,
        on_usage: UsageCallback | None = None,
    ):
        self.provider = provider
        self.fallback_provider = fallback_provider
        self.on_usage = on_usage

    @property
    def name(self) -> str:
        """Return the primary provider name."""
        return self.provider.name

    @property
    def model(self) -> str:
        """Return the primary provider model."""
        return self.provider.model

    async def complete(
        self,
        messages: list[LLMMessage],
        tools: list[dict[str, Any]] | None = None,
        force_tool: str | None = None,
    ) -> LLMResponse:
        """
        Complete an LLM request using the primary provider.

        If the primary provider is unavailable because of quota,
        rate limits, transient errors, or malformed responses,
        the configured fallback provider is attempted.
        """

        # Build provider list.
        providers: list[LLMProvider] = [self.provider]

        if self.fallback_provider is not None:
            providers.append(self.fallback_provider)

        last_error: Exception | None = None

        # ---------------------------------------------------------
        # Try each provider
        # ---------------------------------------------------------

        for provider_index, provider in enumerate(providers):

            log.info(
                "llm_provider_attempt",
                provider=provider.name,
                model=provider.model,
                provider_index=provider_index,
            )

            # -----------------------------------------------------
            # Retry current provider
            # -----------------------------------------------------

            for attempt in range(settings.llm_max_retries):

                try:
                    response = await provider.complete(
                        messages,
                        tools,
                        force_tool,
                    )

                    # ---------------------------------------------
                    # Usage accounting
                    # ---------------------------------------------

                    if self.on_usage:
                        await self.on_usage(
                            response.prompt_tokens,
                            response.completion_tokens,
                        )

                    log.info(
                        "llm_provider_success",
                        provider=provider.name,
                        model=provider.model,
                        attempt=attempt,
                    )

                    return response

                # =================================================
                # RATE LIMIT
                # =================================================

                except RateLimitError as exc:

                    last_error = exc

                    delay = (
                        exc.retry_after
                        if exc.retry_after is not None
                        else min(
                            60.0,
                            2.0 * (2**attempt),
                        )
                    )

                    delay += random.uniform(0, 1.5)

                    log.warning(
                        "llm_rate_limited",
                        provider=provider.name,
                        model=provider.model,
                        attempt=attempt,
                        sleep=round(delay, 1),
                        error=str(exc)[:300],
                    )

                    # If this was the final retry for this provider,
                    # move to the fallback provider.
                    if attempt >= settings.llm_max_retries - 1:
                        break

                    await asyncio.sleep(delay)

                # =================================================
                # TRANSIENT ERROR
                # =================================================

                except TransientError as exc:

                    last_error = exc

                    delay = (
                        min(
                            30.0,
                            1.5 * (2**attempt),
                        )
                        + random.uniform(0, 1)
                    )

                    log.warning(
                        "llm_transient_error",
                        provider=provider.name,
                        model=provider.model,
                        attempt=attempt,
                        sleep=round(delay, 1),
                        error=str(exc)[:300],
                    )

                    if attempt >= settings.llm_max_retries - 1:
                        break

                    await asyncio.sleep(delay)

                # =================================================
                # MALFORMED RESPONSE
                # =================================================

                except MalformedResponseError as exc:

                    last_error = exc

                    log.warning(
                        "llm_malformed_response",
                        provider=provider.name,
                        model=provider.model,
                        attempt=attempt,
                        error=str(exc)[:300],
                    )

                    # Malformed responses usually don't require
                    # long exponential backoff.
                    if attempt >= settings.llm_max_retries - 1:
                        break

                    await asyncio.sleep(1.0)

                # =================================================
                # QUOTA EXHAUSTED
                # =================================================

                except QuotaExhaustedError as exc:

                    last_error = exc

                    log.warning(
                        "llm_quota_exhausted",
                        provider=provider.name,
                        model=provider.model,
                        error=str(exc)[:500],
                    )

                    # IMPORTANT:
                    #
                    # Quota exhaustion is not normally fixed by
                    # retrying the same provider immediately.
                    #
                    # Break out of the retry loop and move to the
                    # fallback provider.
                    break

                # =================================================
                # AUTH ERROR
                # =================================================

                except AuthError as exc:

                    log.error(
                        "llm_auth_error",
                        provider=provider.name,
                        model=provider.model,
                        error=str(exc)[:300],
                    )

                    # Authentication errors should not be retried.
                    #
                    # However, if a fallback provider exists,
                    # allow the fallback to run.
                    last_error = exc
                    break

            # -----------------------------------------------------
            # Move to fallback provider
            # -----------------------------------------------------

            if provider_index < len(providers) - 1:

                next_provider = providers[
                    provider_index + 1
                ]

                log.warning(
                    "llm_switching_provider",
                    from_provider=provider.name,
                    from_model=provider.model,
                    to_provider=next_provider.name,
                    to_model=next_provider.model,
                    reason=(
                        str(last_error)[:300]
                        if last_error
                        else "provider_failed"
                    ),
                )

                continue

        # ---------------------------------------------------------
        # All providers failed
        # ---------------------------------------------------------

        log.error(
            "llm_all_providers_failed",
            primary_provider=self.provider.name,
            fallback_provider=(
                self.fallback_provider.name
                if self.fallback_provider
                else None
            ),
            error=(
                str(last_error)[:500]
                if last_error
                else "unknown error"
            ),
        )

        raise last_error or TransientError(
            "All LLM providers failed"
        )