"""Phase 3c.1 — semantic FAQ lookup using cosine similarity (pgvector).

`lookup_faq(session, tenant_id, embedding, top_k=3, score_threshold=0.5)`
is the function-style interface the runner (T18) calls directly. The
caller is responsible for generating `embedding` (typically via
`generate_embedding(text=user_message)`) and for accumulating its cost
into `turn_traces.tool_cost_usd`.

Cosine similarity is computed via pgvector's `<=>` operator (cosine
distance, in [0, 2]). We expose `score = 1 - distance` in [-1, 1] but in
practice it lives in [0, 1] for normalized embeddings. The default
threshold 0.5 (design doc decision #10) keeps spurious matches out of
the Composer prompt — when the best FAQ is too far, we'd rather redirect
than answer the wrong question.

A legacy `LookupFAQTool(Tool)` wrapper is preserved at the bottom for
`register_all_tools()` compat. It generates a one-off embedding on the
fly using the user's question text — useful for callers that don't have
an embedding pipeline yet, but the runner path (T18) doesn't take it.
"""

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.db.models import TenantFAQ
from atendia.tools.base import FAQMatch, Tool, ToolNoDataResult


async def lookup_faq(
    *,
    session: AsyncSession,
    tenant_id: UUID,
    embedding: list[float],
    top_k: int = 3,
    score_threshold: float = 0.5,
    collection_ids: list[UUID] | None = None,
) -> list[FAQMatch] | ToolNoDataResult:
    """Return the top-k FAQs whose embedding is closest to `embedding`.

    Filters to rows whose cosine similarity score >= `score_threshold`.
    If no row clears the threshold (or the tenant has no embedded FAQs),
    returns `ToolNoDataResult` so the Composer can redirect.

    Rows with `embedding IS NULL` are excluded — the partial-ingestion
    case where some FAQs aren't embedded yet shouldn't break ranking.

    When ``collection_ids`` is non-empty, results are restricted to FAQs
    whose ``collection_id`` is in that list — the runner uses this to
    enforce ``agent.knowledge_config.collection_ids`` so different
    agents on the same tenant can be scoped to different knowledge sets
    (e.g. a "Soporte" agent only sees soporte collections, never sales).
    Empty/None means "no scoping" — every FAQ in the tenant is fair game.
    """
    distance = TenantFAQ.embedding.cosine_distance(embedding)
    stmt = (
        select(TenantFAQ, (1 - distance).label("score"))
        .where(
            TenantFAQ.tenant_id == tenant_id,
            TenantFAQ.embedding.is_not(None),
        )
        .order_by(distance)
        .limit(top_k)
    )
    if collection_ids:
        stmt = stmt.where(TenantFAQ.collection_id.in_(collection_ids))
    rows = (await session.execute(stmt)).all()
    matches = [
        FAQMatch(
            pregunta=faq.question,
            respuesta=faq.answer,
            score=float(score),
            faq_id=faq.id,
            collection_id=faq.collection_id,
        )
        for faq, score in rows
        if float(score) >= score_threshold
    ]
    if not matches:
        return ToolNoDataResult(hint=f"no FAQ above similarity threshold {score_threshold}")
    return matches


class LookupFAQTool(Tool):  # pragma: no cover
    """Legacy registry wrapper — accepts a `question` text and embeds it inline.

    Phase 3c.1's runner (T18) calls `lookup_faq()` directly with a
    pre-computed embedding (so the cost is tracked separately). This
    wrapper exists only so `register_all_tools()` keeps the same six
    tool names; new code paths import the function.
    """

    name = "lookup_faq"

    async def run(self, session: AsyncSession, **kwargs: Any) -> dict:
        # The legacy class-based API takes a `question` string. Generating
        # an embedding here would couple this method to the OpenAI client
        # configuration, so we expect callers to pass `embedding` directly.
        # If they don't, return ToolNoDataResult so the action_resolver
        # path doesn't crash on a missing key.
        embedding = kwargs.get("embedding")
        if not embedding:
            return ToolNoDataResult(
                hint="lookup_faq requires `embedding` kwarg in Phase 3c.1+",
            ).model_dump(mode="json")
        result = await lookup_faq(
            session=session,
            tenant_id=kwargs["tenant_id"],
            embedding=embedding,
            top_k=kwargs.get("top_k", 3),
            score_threshold=kwargs.get("score_threshold", 0.5),
        )
        if isinstance(result, ToolNoDataResult):
            return result.model_dump(mode="json")
        return {"matches": [m.model_dump(mode="json") for m in result]}
