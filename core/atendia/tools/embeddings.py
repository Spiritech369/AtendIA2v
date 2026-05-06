"""OpenAI text-embedding wrapper with cost tracking (Phase 3c.1).

Single chokepoint for every text -> 3072-dim vector conversion. Used both
for one-time ingestion (T15) and per-turn runtime queries (T11, T12).

Cost accounting lives here because every embedding call must contribute
to `turn_traces.tool_cost_usd` (added in migration 014). Returning
`(embedding, tokens, cost_usd)` keeps the caller honest — there's no path
to call OpenAI without surfacing the cost.

The actual `vector` -> `halfvec` cast for storage happens at the edge
(model-mapped column `HALFVEC(3072)` does it transparently), so we deal
in plain `list[float]` here.
"""
from decimal import Decimal

from openai import AsyncOpenAI


# Pricing for text-embedding-3-large at 2026-05: $0.13 per 1M tokens.
# If OpenAI changes published pricing, update this constant; the unit
# test `test_cost_formula_constant` will fail loudly to flag the drift.
EMBEDDING_PRICE_PER_1M: Decimal = Decimal("0.130")

# Model name pinned here so callers don't have to remember it.
DEFAULT_EMBEDDING_MODEL: str = "text-embedding-3-large"


def _compute_cost(tokens: int) -> Decimal:
    """Tokens × price / 1M, rounded to 6 decimals (matches turn_traces.NUMERIC(10,6))."""
    return (Decimal(tokens) * EMBEDDING_PRICE_PER_1M / Decimal("1000000")).quantize(
        Decimal("0.000001")
    )


async def generate_embedding(
    *,
    client: AsyncOpenAI,
    text: str,
    model: str = DEFAULT_EMBEDDING_MODEL,
) -> tuple[list[float], int, Decimal]:
    """Embed a single piece of text.

    Returns ``(embedding, tokens_used, cost_usd)``. The embedding is a
    plain ``list[float]`` of length 3072 (text-embedding-3-large). The
    cost is already quantized to 6 decimals so it can be stored as-is.
    """
    resp = await client.embeddings.create(model=model, input=text)
    return (
        list(resp.data[0].embedding),
        resp.usage.total_tokens,
        _compute_cost(resp.usage.total_tokens),
    )


async def generate_embeddings_batch(
    *,
    client: AsyncOpenAI,
    texts: list[str],
    model: str = DEFAULT_EMBEDDING_MODEL,
) -> tuple[list[list[float]], int, Decimal]:
    """Embed N texts in a single API call.

    OpenAI's Embeddings endpoint accepts a list-of-strings input, so for
    ingestion we batch the entire catalog or FAQ corpus into one round
    trip. Empty input short-circuits without making the call (zero tokens,
    zero cost) so callers can pass arbitrary lists without guarding.

    Returns ``(embeddings, total_tokens, total_cost_usd)``.
    """
    if not texts:
        return [], 0, Decimal("0")
    resp = await client.embeddings.create(model=model, input=texts)
    return (
        [list(item.embedding) for item in resp.data],
        resp.usage.total_tokens,
        _compute_cost(resp.usage.total_tokens),
    )
