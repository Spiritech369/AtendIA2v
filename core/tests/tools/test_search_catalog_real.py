"""T12 — Tests for hybrid `search_catalog()` (Phase 3c.1).

The hybrid strategy (design doc decision #9):

  1. **Alias-keyword first** — JSONB `?|` against `attrs.alias` (lowercased
     to match the stored alias list). Cheap, exact, no embedding cost.
     When the customer says "Adventure" or "Rayo", they know the model.
  2. **Semantic fallback** — only when no alias matches AND the caller
     supplies a query embedding. For phrasings like "una motoneta urbana"
     where there's no exact lexical match.
  3. **ToolNoDataResult** — when neither produces results, so the
     Composer redirects ("¿podrías decirme qué modelo te interesa?").
"""

import pytest
from sqlalchemy import text

from atendia.db.models import TenantCatalogItem
from atendia.tools.base import CatalogResult, ToolNoDataResult
from atendia.tools.search_catalog import search_catalog

pytestmark = pytest.mark.asyncio


def _emb(seed: int, dim: int = 3072) -> list[float]:
    """Unit vector pointing at axis `seed`."""
    v = [0.0] * dim
    v[seed] = 1.0
    return v


async def _seed_item(
    session,
    tenant_id,
    *,
    sku: str,
    name: str,
    category: str = "Motoneta",
    alias: list[str] | None = None,
    embedding: list[float] | None = None,
    active: bool = True,
    precio_contado: str = "29900",
) -> None:
    """ORM insert of a catalog item — handles halfvec round-trip cleanly."""
    session.add(
        TenantCatalogItem(
            tenant_id=tenant_id,
            sku=sku,
            name=name,
            category=category,
            attrs={"alias": alias or [], "precio_contado": precio_contado},
            embedding=embedding,
            active=active,
        )
    )


async def test_alias_keyword_match(db_session) -> None:
    """Lower-cased alias hit returns CatalogResult with score=1.0 (exact)."""
    tid = (
        await db_session.execute(
            text("INSERT INTO tenants (name) VALUES ('test_t12_alias') RETURNING id")
        )
    ).scalar()
    await _seed_item(
        db_session,
        tid,
        sku="adventure-150",
        name="Adventure 150",
        alias=["adventure", "elite"],
        embedding=_emb(0),
    )
    await db_session.commit()
    try:
        result = await search_catalog(
            session=db_session,
            tenant_id=tid,
            query="adventure",
            embedding=None,
        )
        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], CatalogResult)
        assert result[0].sku == "adventure-150"
        assert result[0].score == 1.0  # alias hit is treated as exact
    finally:
        await db_session.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": tid})
        await db_session.commit()


async def test_alias_match_is_case_insensitive(db_session) -> None:
    """User typed 'ADVENTURE' but aliases are stored lowercase — still hits."""
    tid = (
        await db_session.execute(
            text("INSERT INTO tenants (name) VALUES ('test_t12_case') RETURNING id")
        )
    ).scalar()
    await _seed_item(
        db_session, tid, sku="adv-1", name="Adventure", alias=["adventure"], embedding=_emb(0)
    )
    await db_session.commit()
    try:
        result = await search_catalog(
            session=db_session,
            tenant_id=tid,
            query="ADVENTURE",
            embedding=None,
        )
        assert isinstance(result, list)
        assert result[0].sku == "adv-1"
    finally:
        await db_session.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": tid})
        await db_session.commit()


async def test_falls_back_to_no_data_when_no_alias_and_no_embedding(db_session) -> None:
    """No alias match and embedding=None → ToolNoDataResult."""
    tid = (
        await db_session.execute(
            text("INSERT INTO tenants (name) VALUES ('test_t12_no_alias_no_emb') RETURNING id")
        )
    ).scalar()
    await _seed_item(db_session, tid, sku="x-1", name="X", alias=["other"], embedding=_emb(0))
    await db_session.commit()
    try:
        result = await search_catalog(
            session=db_session,
            tenant_id=tid,
            query="nonexistent",
            embedding=None,
        )
        assert isinstance(result, ToolNoDataResult)
        assert "nonexistent" in result.hint
    finally:
        await db_session.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": tid})
        await db_session.commit()


async def test_semantic_fallback_when_alias_misses(db_session) -> None:
    """No alias hit but caller passes embedding → cosine search returns top match."""
    tid = (
        await db_session.execute(
            text("INSERT INTO tenants (name) VALUES ('test_t12_semantic') RETURNING id")
        )
    ).scalar()
    await _seed_item(db_session, tid, sku="x-1", name="X", alias=["other"], embedding=_emb(0))
    await db_session.commit()
    try:
        result = await search_catalog(
            session=db_session,
            tenant_id=tid,
            query="something else",
            embedding=_emb(0),
        )
        assert isinstance(result, list)
        assert result[0].sku == "x-1"
        assert result[0].score >= 0.99
    finally:
        await db_session.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": tid})
        await db_session.commit()


async def test_respects_limit(db_session) -> None:
    """Returning at most `limit` rows even if many match the alias."""
    tid = (
        await db_session.execute(
            text("INSERT INTO tenants (name) VALUES ('test_t12_limit') RETURNING id")
        )
    ).scalar()
    # All share alias "shared" so they all match — count must still cap.
    for i in range(10):
        await _seed_item(
            db_session, tid, sku=f"sku-{i}", name=f"Name {i}", alias=["shared"], embedding=_emb(i)
        )
    await db_session.commit()
    try:
        result = await search_catalog(
            session=db_session,
            tenant_id=tid,
            query="shared",
            embedding=None,
            limit=3,
        )
        assert isinstance(result, list)
        assert len(result) == 3
    finally:
        await db_session.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": tid})
        await db_session.commit()


async def test_filters_inactive(db_session) -> None:
    """Inactive items must not appear in either alias or semantic results."""
    tid = (
        await db_session.execute(
            text("INSERT INTO tenants (name) VALUES ('test_t12_inactive') RETURNING id")
        )
    ).scalar()
    await _seed_item(
        db_session,
        tid,
        sku="old-1",
        name="Old",
        category="Motoneta",
        alias=["old"],
        embedding=None,
        active=False,
    )
    await db_session.commit()
    try:
        result = await search_catalog(
            session=db_session,
            tenant_id=tid,
            query="old",
            embedding=None,
        )
        assert isinstance(result, ToolNoDataResult)
    finally:
        await db_session.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": tid})
        await db_session.commit()


async def test_tenant_isolation(db_session) -> None:
    """Items from another tenant must not leak into search results."""
    tid_a = (
        await db_session.execute(
            text("INSERT INTO tenants (name) VALUES ('test_t12_iso_a') RETURNING id")
        )
    ).scalar()
    tid_b = (
        await db_session.execute(
            text("INSERT INTO tenants (name) VALUES ('test_t12_iso_b') RETURNING id")
        )
    ).scalar()
    await _seed_item(
        db_session, tid_b, sku="leaked", name="Leak", alias=["unique"], embedding=_emb(0)
    )
    await db_session.commit()
    try:
        result = await search_catalog(
            session=db_session,
            tenant_id=tid_a,
            query="unique",
            embedding=_emb(0),
        )
        assert isinstance(result, ToolNoDataResult)
    finally:
        await db_session.execute(
            text("DELETE FROM tenants WHERE id IN (:a, :b)"),
            {"a": tid_a, "b": tid_b},
        )
        await db_session.commit()


async def test_alias_match_is_deterministic_with_limit(db_session) -> None:
    """Sprint C.6 — when multiple SKUs share the same alias and the caller
    passes `limit=1`, the same SKU must come back every call.

    Before the fix the query did `.limit(1)` with no `ORDER BY`, so
    Postgres returned whichever row its planner scanned first — and
    that changed between runs / vacuum cycles. Operators saw a quote
    pin to product A on one turn and product B on the next, with no
    way to predict or test which one.
    """
    tid = (
        await db_session.execute(
            text("INSERT INTO tenants (name) VALUES ('test_t12_disambig') RETURNING id")
        )
    ).scalar()
    # Three SKUs all aliased "rayo" — classic disambiguation trap.
    await _seed_item(db_session, tid, sku="rayo-150", name="Rayo 150", alias=["rayo"])
    await _seed_item(db_session, tid, sku="rayo-125", name="Rayo 125", alias=["rayo"])
    await _seed_item(db_session, tid, sku="rayo-200", name="Rayo 200", alias=["rayo"])
    await db_session.commit()
    try:
        firsts: set[str] = set()
        for _ in range(10):
            result = await search_catalog(
                session=db_session,
                tenant_id=tid,
                query="rayo",
                embedding=None,
                limit=1,
            )
            assert isinstance(result, list)
            assert len(result) == 1
            firsts.add(result[0].sku)
        assert len(firsts) == 1, f"search_catalog with limit=1 must be deterministic; got {firsts}"
        # And the deterministic choice should be the alphabetically-lowest sku
        # so two operators reading the runbook can predict which one wins.
        assert firsts == {"rayo-125"}
    finally:
        await db_session.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": tid})
        await db_session.commit()
