"""Provider selection."""

from __future__ import annotations

from app.agent.providers.base import Message, Provider, ToolCall, Turn
from app.config import get_settings


class NoProviderKey(Exception):
    """No credential for the selected provider.

    Raised rather than silently falling back: a run that could not use the model
    must never be presented as an AI run.
    """


def get_provider() -> Provider:
    settings = get_settings()
    if settings.ai_provider == "anthropic":
        if not settings.anthropic_api_key:
            raise NoProviderKey("ANTHROPIC_API_KEY is not set.")
        from app.agent.providers.anthropic_provider import AnthropicProvider
        return AnthropicProvider(settings.anthropic_api_key, settings.ai_model)

    if not settings.gemini_api_key:
        raise NoProviderKey("GEMINI_API_KEY is not set.")
    from app.agent.providers.gemini import GeminiProvider
    return GeminiProvider(settings.gemini_api_key, settings.ai_model)


__all__ = ["Message", "Provider", "ToolCall", "Turn", "get_provider", "NoProviderKey"]
