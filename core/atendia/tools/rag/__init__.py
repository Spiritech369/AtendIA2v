"""KB-module RAG package.

Provider Protocol + concrete OpenAI/Mock providers + selection helper
arrive in Tasks 8-9. The retriever, prompt builder, and synthesizer
land in Phase 2 (Tasks 13-15).
"""
from __future__ import annotations

from atendia.tools.rag.mock_provider import MockProvider
from atendia.tools.rag.provider import AnswerOutput, LLMProvider, PromptInput

__all__ = ["AnswerOutput", "LLMProvider", "MockProvider", "PromptInput"]
