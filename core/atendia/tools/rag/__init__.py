"""KB-module RAG package.

``get_provider()`` returns the singleton provider chosen via
``KB_PROVIDER`` (or auto-falls back to mock when ``OPENAI_API_KEY`` is
empty). Cached per process — call ``get_provider.cache_clear()`` from
test fixtures that monkeypatch settings.
"""
from __future__ import annotations

from functools import lru_cache

from atendia.config import get_settings
from atendia.tools.rag.mock_provider import MockProvider
from atendia.tools.rag.openai_provider import OpenAIProvider
from atendia.tools.rag.provider import AnswerOutput, LLMProvider, PromptInput


@lru_cache(maxsize=1)
def get_provider() -> LLMProvider:
    settings = get_settings()
    if settings.kb_provider == "mock" or not settings.openai_api_key:
        return MockProvider()
    return OpenAIProvider(settings.openai_api_key)


__all__ = [
    "AnswerOutput",
    "LLMProvider",
    "MockProvider",
    "OpenAIProvider",
    "PromptInput",
    "get_provider",
]
