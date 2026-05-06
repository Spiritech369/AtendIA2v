"""Phase 3c.1 — hybrid catalog search (alias-keyword first, semantic fallback).

`search_catalog(session, tenant_id, query, embedding=None, limit=5)` is the
function-style interface the runner (T18) calls when the customer is browsing
("muéstrame motonetas urbanas") instead of asking for a specific SKU.

Strategy (design doc decision #9):

  Path 1 — alias-keyword. JSONB `?|` against `attrs.alias` (which ingestion
  populates lowercased). Cheap, exact, no embedding cost. Score is hardcoded
  to 1.0 because alias hits are categorically more reliable than semantic.

  Path 2 — semantic fallback. Only fires when (a) no alias matched AND (b)
  the caller passed an `embedding`. Uses pgvector cosine distance with the
  HNSW index from migration 013. Score is `1 - cosine_distance` ∈ [-1, 1].

  Path 3 — no match. Returns `ToolNoDataResult` with a hint that mentions
  the original query so the Composer can echo it ("no encontré 'lambretta',
  ¿quieres ver lo que sí tenemos?").

Why this order: customers searching by model name are ~80% of catalog
queries. Doing alias first costs ~1 ms and avoids paying the embedding
API call for all those queries. Semantic only kicks in for the long tail.
"""
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.db.models import TenantCatalogItem
from atendia.tools.base import CatalogResult, Tool, ToolNoDataResult


def _to_result(item: TenantCatalogItem, *, score: float) -> CatalogResult:
    """Project a TenantCatalogItem row into the lighter CatalogResult shape."""
    attrs = item.attrs or {}
    return CatalogResult(
        sku=item.sku,
        name=item.name,
        category=item.category or "",
        price_contado_mxn=Decimal(str(attrs.get("precio_contado", "0"))),
        score=score,
    )


async def search_catalog(
    *,
    session: AsyncSession,
    tenant_id: UUID,
    query: str,
    embedding: list[float] | None = None,
    limit: int = 5,
) -> list[CatalogResult] | ToolNoDataResult:
    """Hybrid alias-keyword + semantic catalog lookup.

    `query` is the raw user text or extracted entity. It's lowercased
    before matching against `attrs.alias`. `embedding` is optional —
    when provided, it's used as the semantic fallback query vector.
    Pass `None` to skip semantic entirely (saves the API call when the
    caller knows alias-keyword is sufficient).
    """
    # Path 1: alias-keyword match. JSONB `?|` is "any-of" — true if the
    # array contains any element from the right-hand array.
    keyword_stmt = (
        select(TenantCatalogItem)
        .where(
            TenantCatalogItem.tenant_id == tenant_id,
            TenantCatalogItem.active.is_(True),
            text("attrs->'alias' ?| ARRAY[:alias_q]").bindparams(alias_q=query.lower()),
        )
        .limit(limit)
    )
    keyword_hits = (await session.execute(keyword_stmt)).scalars().all()
    if keyword_hits:
        return [_to_result(item, score=1.0) for item in keyword_hits]

    # Path 2: semantic fallback. Only when caller supplied an embedding.
    if embedding is None:
        return ToolNoDataResult(
            hint=f"no alias match for {query!r}; semantic search not invoked"
        )

    distance = TenantCatalogItem.embedding.cosine_distance(embedding)
    semantic_stmt = (
        select(TenantCatalogItem, (1 - distance).label("score"))
        .where(
            TenantCatalogItem.tenant_id == tenant_id,
            TenantCatalogItem.active.is_(True),
            TenantCatalogItem.embedding.is_not(None),
        )
        .order_by(distance)
        .limit(limit)
    )
    rows = (await session.execute(semantic_stmt)).all()
    if not rows:
        return ToolNoDataResult(hint=f"no semantic match for {query!r}")
    return [_to_result(item, score=float(score)) for item, score in rows]


class SearchCatalogTool(Tool):
    """Legacy registry wrapper — delegates to `search_catalog()`.

    Phase 3c.1's runner (T18) calls `search_catalog()` directly, so this
    wrapper exists only to keep `register_all_tools()` returning the same
    six tool names. Embedding generation is the caller's responsibility
    (so the cost lands in `tool_cost_usd`); without one, this falls back
    to alias-only search.
    """

    name = "search_catalog"

    async def run(self, session: AsyncSession, **kwargs: Any) -> dict:
        result = await search_catalog(
            session=session,
            tenant_id=kwargs["tenant_id"],
            query=kwargs.get("query", ""),
            embedding=kwargs.get("embedding"),
            limit=kwargs.get("limit", 5),
        )
        if isinstance(result, ToolNoDataResult):
            return result.model_dump(mode="json")
        return {"results": [r.model_dump(mode="json") for r in result]}
