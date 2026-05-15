"""Protocol + DTOs for the LLM provider abstraction used by the KB module.

Two implementations live alongside this file:

* ``OpenAIProvider`` — production path; wraps ``atendia.tools.embeddings``
  for embeddings and ``openai.AsyncOpenAI`` for chat completion.
* ``MockProvider`` — deterministic SHA-256-based embeddings + templated
  answers, used by tests and offline dev (``KB_PROVIDER=mock``).

The module is intentionally tiny — keeping it free of imports of the
two providers themselves means tests can import ``MockProvider``
without pulling in the OpenAI SDK.
"""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel


class PromptInput(BaseModel):
    """Inputs for ``generate_answer`` — kept dialect-neutral so the
    OpenAI and mock implementations agree on what they receive."""

    system: str
    user: str
    context: str
    response_instructions: str
    model: str
    max_tokens: int
    temperature: float


class AnswerOutput(BaseModel):
    """What ``generate_answer`` returns — answer text plus cost/token
    metadata for the audit trail. Fields are optional so the mock
    provider can omit fields that don't apply (cost_usd=0)."""

    text: str
    raw_response: dict | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    cost_usd: float | None = None


class LLMProvider(Protocol):
    async def create_embedding(self, text: str) -> list[float]: ...
    async def generate_answer(self, prompt: PromptInput) -> AnswerOutput: ...
