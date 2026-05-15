"""T9 — Tests for the OpenAI embeddings wrapper.

The wrapper is the single chokepoint where every text -> vector conversion
happens, so this is also where cost accounting lives. Tests are mock-only
(respx) — live calls happen in T15's ingestion run.
"""

from decimal import Decimal

import respx
from httpx import Response
from openai import AsyncOpenAI

from atendia.tools.embeddings import (
    EMBEDDING_PRICE_PER_1M,
    generate_embedding,
    generate_embeddings_batch,
)


def _ok_embeddings_response(num: int, dim: int = 3072, total_tokens: int = 100) -> Response:
    """Mock the OpenAI Embeddings API response shape."""
    return Response(
        200,
        json={
            "object": "list",
            "data": [
                {"object": "embedding", "index": i, "embedding": [0.1] * dim} for i in range(num)
            ],
            "model": "text-embedding-3-large",
            "usage": {"prompt_tokens": total_tokens, "total_tokens": total_tokens},
        },
    )


@respx.mock
async def test_generate_embedding_single() -> None:
    """Single-text path returns the embedding, raw token count, and computed cost."""
    respx.post("https://api.openai.com/v1/embeddings").mock(
        return_value=_ok_embeddings_response(num=1, total_tokens=10),
    )
    client = AsyncOpenAI(api_key="sk-test")
    emb, tokens, cost = await generate_embedding(client=client, text="hola")
    assert len(emb) == 3072
    assert tokens == 10
    # 10 * 0.13 / 1M = 0.0000013 → quantized to 6 decimals = 0.000001
    assert cost == Decimal("0.000001")


@respx.mock
async def test_generate_embeddings_batch() -> None:
    """Batch path collapses N texts into a single API call."""
    respx.post("https://api.openai.com/v1/embeddings").mock(
        return_value=_ok_embeddings_response(num=50, total_tokens=5000),
    )
    client = AsyncOpenAI(api_key="sk-test")
    embs, tokens, cost = await generate_embeddings_batch(
        client=client,
        texts=[f"texto {i}" for i in range(50)],
    )
    assert len(embs) == 50
    assert all(len(e) == 3072 for e in embs)
    assert tokens == 5000
    # 5000 * 0.13 / 1M = 0.00065 → "0.000650"
    assert cost == Decimal("0.000650")


async def test_generate_embeddings_batch_empty() -> None:
    """Empty input list short-circuits without an API call (no cost, no tokens)."""
    client = AsyncOpenAI(api_key="sk-test")
    embs, tokens, cost = await generate_embeddings_batch(client=client, texts=[])
    assert embs == []
    assert tokens == 0
    assert cost == Decimal("0")


def test_cost_formula_constant() -> None:
    """Pricing constant matches OpenAI text-embedding-3-large at 2026-05.

    If OpenAI changes the published price, this test will fail loudly so we
    update both the constant and any cost assertions in T15/T19.
    """
    assert EMBEDDING_PRICE_PER_1M == Decimal("0.130")
