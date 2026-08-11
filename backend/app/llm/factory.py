"""Provider selection from environment configuration."""
from __future__ import annotations

from app.config import settings
from app.llm.base import AuthError, LLMProvider
from app.llm.gemini_provider import GeminiProvider
from app.llm.groq_provider import GroqProvider


def get_provider() -> LLMProvider:
    provider = settings.llm_provider.strip().lower()
    if provider == "gemini":
        if not settings.gemini_api_key:
            raise AuthError(
                "LLM_PROVIDER=gemini but GEMINI_API_KEY is empty — set it in backend/.env"
            )
        return GeminiProvider(settings.gemini_api_key, settings.gemini_model)
    if provider == "groq":
        if not settings.groq_api_key:
            raise AuthError(
                "LLM_PROVIDER=groq but GROQ_API_KEY is empty — set it in backend/.env"
            )
        return GroqProvider(settings.groq_api_key, settings.groq_model)
    raise ValueError(f"Unknown LLM_PROVIDER '{settings.llm_provider}' (use 'gemini' or 'groq')")
