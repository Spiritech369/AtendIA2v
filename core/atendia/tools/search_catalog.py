"""Hybrid catalog search (alias-keyword first, semantic fallback).

`search_catalog(session, tenant_id, query, embedding=None, limit=5)` is the
function-style interface the runner calls when the customer is browsing
instead of asking for a specific SKU.

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

from atendia.catalog_runtime import catalog_cash_price_mxn
from atendia.commercial_catalog_service import (
    has_published_catalogs,
    search_catalog as search_published_catalog,
)
from atendia.db.models import TenantCatalogItem
from atendia.text_normalization import normalize_whatsapp_text
from atendia.tools.base import CatalogResult, Tool, ToolNoDataResult


def _to_result(item: TenantCatalogItem, *, score: float) -> CatalogResult:
    """Project a TenantCatalogItem row into the lighter CatalogResult shape."""
    return CatalogResult(
        sku=item.sku,
        name=item.name,
        category=item.category or "",
        cash_price_mxn=Decimal(str(catalog_cash_price_mxn(item) or "0")),
        score=score,
        catalog_item_id=item.id,
        collection_id=item.collection_id,
    )


async def search_catalog(
    *,
    session: AsyncSession,
    tenant_id: UUID,
    query: str,
    embedding: list[float] | None = None,
    limit: int = 5,
    collection_ids: list[UUID] | None = None,
) -> list[CatalogResult] | ToolNoDataResult:
    """Hybrid alias-keyword + semantic catalog lookup.

    `query` is the raw user text or extracted entity. It's lowercased
    before matching against `attrs.alias`. `embedding` is optional —
    when provided, it's used as the semantic fallback query vector.
    Pass `None` to skip semantic entirely (saves the API call when the
    caller knows alias-keyword is sufficient).

    ``collection_ids`` restricts results to catalog items inside those
    collections — used to enforce ``agent.knowledge_config.collection_ids``
    so each agent only sees the products it's supposed to. Empty/None
    means no scoping.
    """
    # Path 1: alias-keyword match. JSONB `?|` is "any-of" — true if the
    # array contains any element from the right-hand array.
    #
    # Sprint C.6: alphabetical `sku` order is the tiebreaker so a query
    # like "rayo" against three SKUs sharing that alias always picks the
    # same row across calls. Without the ORDER BY, Postgres returned
    # whichever row its planner scanned first and that changed between
    # vacuum cycles — quotes pinned to a different product silently.
    normalized_query = normalize_whatsapp_text(query, keep_percent=False) or query
    published_hits = await search_published_catalog(
        session,
        tenant_id=tenant_id,
        query=normalized_query,
        limit=limit,
    )
    if published_hits:
        results: list[CatalogResult] = []
        for match in published_hits:
            item = match.item
            cash_price = item.get("base_price")
            if cash_price in (None, ""):
                cash_price = item.get("list_price")
            results.append(
                CatalogResult(
                    sku=str(item.get("sku") or ""),
                    name=str(item.get("name") or ""),
                    category=str(item.get("category") or ""),
                    cash_price_mxn=Decimal(str(cash_price or "0")),
                    score=float(match.score),
                    catalog_item_id=None,
                    collection_id=None,
                    source={
                        "catalog_source": "atendia_catalog_published",
                        "catalog_id": str(match.catalog_id),
                        "catalog_name": match.catalog_name,
                    },
                )
            )
        return results
    if await has_published_catalogs(session, tenant_id=tenant_id):
        return ToolNoDataResult(hint=f"no published catalog match for {query!r}")

    keyword_stmt = (
        select(TenantCatalogItem)
        .where(
            TenantCatalogItem.tenant_id == tenant_id,
            TenantCatalogItem.active.is_(True),
            text("attrs->'alias' ?| ARRAY[:alias_q]").bindparams(
                alias_q=normalized_query.lower()
            ),
        )
        .order_by(TenantCatalogItem.sku)
        .limit(limit)
    )
    if collection_ids:
        keyword_stmt = keyword_stmt.where(TenantCatalogItem.collection_id.in_(collection_ids))
    keyword_hits = (await session.execute(keyword_stmt)).scalars().all()
    if keyword_hits:
        return [_to_result(item, score=1.0) for item in keyword_hits]

    # Path 2: semantic fallback. Only when caller supplied an embedding.
    if embedding is None:
        return ToolNoDataResult(hint=f"no alias match for {query!r}; semantic search not invoked")

    distance = TenantCatalogItem.embedding.cosine_distance(embedding)
    # `sku` is the secondary order so cosine ties (rare but possible
    # when two embeddings collide) resolve deterministically. Sprint C.6.
    semantic_stmt = (
        select(TenantCatalogItem, (1 - distance).label("score"))
        .where(
            TenantCatalogItem.tenant_id == tenant_id,
            TenantCatalogItem.active.is_(True),
            TenantCatalogItem.embedding.is_not(None),
        )
        .order_by(distance, TenantCatalogItem.sku)
        .limit(limit)
    )
    if collection_ids:
        semantic_stmt = semantic_stmt.where(TenantCatalogItem.collection_id.in_(collection_ids))
    rows = (await session.execute(semantic_stmt)).all()
    if not rows:
        return ToolNoDataResult(hint=f"no semantic match for {query!r}")
    return [_to_result(item, score=float(score)) for item, score in rows]


class SearchCatalogTool(Tool):  # pragma: no cover
    """Registry adapter for the function-style catalog search."""

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
