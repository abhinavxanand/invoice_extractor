from __future__ import annotations

import os

from invoice_extractor.llm.base import LLMProvider


def get_provider() -> LLMProvider:
    provider_name = os.environ.get("LLM_PROVIDER", "fake").lower()

    if provider_name == "fake":
        from invoice_extractor.llm.fake_provider import FakeProvider
        return FakeProvider()
    elif provider_name == "anthropic":
        from invoice_extractor.llm.anthropic_provider import AnthropicProvider
        return AnthropicProvider()
    elif provider_name == "gemini":
        from invoice_extractor.llm.gemini_provider import GeminiProvider
        return GeminiProvider()
    else:
        raise ValueError(f"Unknown LLM provider: {provider_name}")
