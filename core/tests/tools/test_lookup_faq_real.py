"""T11 — Tests for the semantic `lookup_faq()` function (Phase 3c.1).

Hits the real Postgres + tenant_faqs table with halfvec embeddings.
Synthesises orthogonal unit vectors as test embeddings: vector with a
single 1.0 at position `seed` and zeros elsewhere. Cosine similarity
between two such vectors is 1.0 if same seed, 0.0 if different — a clean
ground truth for the score-threshold logic without needing real OpenAI calls.

Tests use SQLAlchemy ORM inserts because raw SQL would require an explicit
`::halfvec` text cast for each bound parameter; the ORM column-type
machinery binds `list[float]` to halfvec transparently.
"""

import pytest
from sqlalchemy import text

from atendia.db.models import TenantFAQ
from atendia.tools.base import FAQMatch, ToolNoDataResult
from atendia.tools.lookup_faq import lookup_faq


pytestmark = pytest.mark.asyncio


def _emb(seed: int, dim: int = 3072) -> list[float]:
    """Unit vector pointing at axis `seed` (zero everywhere else)."""
    v = [0.0] * dim
    v[seed] = 1.0
    return v


async def test_lookup_faq_returns_top_k_matches(db_session) -> None:
    """5 orthogonal FAQs seeded; query == axis 0 → top result is FAQ 0 with score 1.0."""
    tid = (
        await db_session.execute(
            text("INSERT INTO tenants (name) VALUES ('test_t11_topk') RETURNING id")
        )
    ).scalar()
    for i in range(5):
        db_session.add(
            TenantFAQ(
                tenant_id=tid,
                question=f"pregunta {i}",
                answer=f"respuesta {i}",
                embedding=_emb(i),
            )
        )
    await db_session.commit()
    try:
        result = await lookup_faq(
            session=db_session,
            tenant_id=tid,
            embedding=_emb(0),
            top_k=3,
        )
        # The seeded FAQs are pairwise orthogonal except for the matching one,
        # so only FAQ 0 clears the default score_threshold=0.5. The others
        # have cosine similarity 0 -> score 0 < threshold -> filtered out.
        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], FAQMatch)
        assert result[0].pregunta == "pregunta 0"
        assert result[0].respuesta == "respuesta 0"
        assert result[0].score >= 0.99  # ~ 1.0 after halfvec round-trip
    finally:
        await db_session.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": tid})
        await db_session.commit()


async def test_lookup_faq_returns_no_data_when_below_threshold(db_session) -> None:
    """Single FAQ orthogonal to the query → score 0 < threshold → ToolNoDataResult."""
    tid = (
        await db_session.execute(
            text("INSERT INTO tenants (name) VALUES ('test_t11_below') RETURNING id")
        )
    ).scalar()
    db_session.add(
        TenantFAQ(
            tenant_id=tid,
            question="preg",
            answer="resp",
            embedding=_emb(100),
        )
    )
    await db_session.commit()
    try:
        # Query embedding is orthogonal to the seeded FAQ.
        result = await lookup_faq(
            session=db_session,
            tenant_id=tid,
            embedding=_emb(0),
            top_k=3,
            score_threshold=0.5,
        )
        assert isinstance(result, ToolNoDataResult)
        assert result.status == "no_data"
        assert "threshold" in result.hint.lower()
    finally:
        await db_session.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": tid})
        await db_session.commit()


async def test_lookup_faq_skips_null_embeddings(db_session) -> None:
    """FAQ rows with embedding=NULL must not appear in results.

    Partial ingestion (some rows embedded, others not) is realistic during
    rollout — the tool must gracefully skip un-embedded rows rather than
    crash or rank them badly.
    """
    tid = (
        await db_session.execute(
            text("INSERT INTO tenants (name) VALUES ('test_t11_nulls') RETURNING id")
        )
    ).scalar()
    db_session.add(
        TenantFAQ(
            tenant_id=tid,
            question="no embedding",
            answer="x",
            embedding=None,
        )
    )
    db_session.add(
        TenantFAQ(
            tenant_id=tid,
            question="with embedding",
            answer="y",
            embedding=_emb(0),
        )
    )
    await db_session.commit()
    try:
        result = await lookup_faq(
            session=db_session,
            tenant_id=tid,
            embedding=_emb(0),
        )
        assert isinstance(result, list)
        # Only the embedded row qualifies; the NULL one must not appear.
        assert all(m.pregunta != "no embedding" for m in result)
        assert any(m.pregunta == "with embedding" for m in result)
    finally:
        await db_session.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": tid})
        await db_session.commit()


async def test_lookup_faq_respects_tenant_isolation(db_session) -> None:
    """A FAQ from a different tenant must never appear in results."""
    tid_a = (
        await db_session.execute(
            text("INSERT INTO tenants (name) VALUES ('test_t11_iso_a') RETURNING id")
        )
    ).scalar()
    tid_b = (
        await db_session.execute(
            text("INSERT INTO tenants (name) VALUES ('test_t11_iso_b') RETURNING id")
        )
    ).scalar()
    db_session.add(
        TenantFAQ(
            tenant_id=tid_b,
            question="other tenant",
            answer="should not leak",
            embedding=_emb(0),
        )
    )
    await db_session.commit()
    try:
        result = await lookup_faq(
            session=db_session,
            tenant_id=tid_a,
            embedding=_emb(0),
        )
        assert isinstance(result, ToolNoDataResult)
    finally:
        await db_session.execute(
            text("DELETE FROM tenants WHERE id IN (:a, :b)"), {"a": tid_a, "b": tid_b}
        )
        await db_session.commit()
