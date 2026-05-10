"""Deterministic offline provider for the KB module.

Used by tests and for ``KB_PROVIDER=mock`` dev mode. The embedding is a
SHA-256-stretched 3072-dim unit vector, so cosine similarity behaves
sanely against real chunks stored as halfvec(3072). The chat-completion
stand-in echoes the first ~120 chars of the context so tests can assert
that citations propagated end-to-end.
"""
from __future__ import annotations

import hashlib
import math

from atendia.tools.rag.provider import AnswerOutput, PromptInput

_EMBED_DIM = 3072


class MockProvider:
    async def create_embedding(self, text: str) -> list[float]:
        # Stretch SHA-256 (32B) to 3072 floats by re-hashing with index. The
        # input is normalized (whitespace-trimmed + lowercased) so trivial
        # variants of the same text still hash identically.
        out: list[float] = []
        normalized = text.strip().lower()
        i = 0
        while len(out) < _EMBED_DIM:
            digest = hashlib.sha256(f"{normalized}|{i}".encode("utf-8")).digest()
            for b in digest:
                out.append((b / 255.0) * 2.0 - 1.0)  # ∈ [-1, 1]
                if len(out) == _EMBED_DIM:
                    break
            i += 1
        norm = math.sqrt(sum(x * x for x in out)) or 1.0
        return [x / norm for x in out]

    async def generate_answer(self, prompt: PromptInput) -> AnswerOutput:
        snippet = prompt.context.strip().replace("\n", " ")[:120]
        text = f"[mock] Basado en las fuentes: {snippet}"
        return AnswerOutput(
            text=text,
            raw_response={"mock": True},
            tokens_in=len(prompt.system) // 4,
            tokens_out=len(text) // 4,
            cost_usd=0.0,
        )
