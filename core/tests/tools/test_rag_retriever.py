"""Integration tests for the agent-scoped retriever.

Uses ``MockProvider`` for embeddings — its SHA-256-derived vectors are
deterministic, so the same query and chunk text yield identical
embeddings and a cosine distance of 0 (i.e. similarity 1.0) on exact-
match recall. That lets us assert exact source membership without
relying on OpenAI."""

from __future__ import annotations

from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from atendia.config import get_settings
from atendia.scripts.seed_knowledge_defaults import seed_for_tenant
from atendia.tools.rag.mock_provider import MockProvider
from atendia.tools.rag.retriever import retrieve


@pytest.fixture
async def db_session():
    engine = create_async_engine(get_settings().database_url)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with Session() as session:
        yield session
    await engine.dispose()


@pytest.fixture
async def seeded_tenant(db_session):
    """Tenant with all 9 default collections + 4 agent permissions seeded."""
    eng = create_async_engine(get_settings().database_url)
    async with eng.begin() as conn:
        tid = (
            await conn.execute(
                text("INSERT INTO tenants (name) VALUES ('test_kb_retriever') RETURNING id")
            )
        ).scalar()
    await eng.dispose()

    await seed_for_tenant(db_session, tid)

    yield tid

    eng = create_async_engine(get_settings().database_url)
    async with eng.begin() as conn:
        await conn.execute(text("DELETE FROM tenants WHERE id=:t"), {"t": tid})
    await eng.dispose()


async def _collection_id(session: AsyncSession, tenant_id: UUID, slug: str) -> UUID:
    return (
        await session.execute(
            text("SELECT id FROM kb_collections WHERE tenant_id=:t AND slug=:s"),
            {"t": tenant_id, "s": slug},
        )
    ).scalar_one()


async def _insert_faq(
    session: AsyncSession,
    tenant_id: UUID,
    *,
    question: str,
    answer: str,
    collection_slug: str | None = None,
    status: str = "published",
    expires_at_sql: str | None = None,
) -> UUID:
    coll_id = await _collection_id(session, tenant_id, collection_slug) if collection_slug else None
    provider = MockProvider()
    embedding = await provider.create_embedding(f"{question}\n{answer}")
    embedding_lit = "[" + ",".join(f"{x:.6f}" for x in embedding) + "]"
    expires_clause = expires_at_sql or "NULL"
    fid = (
        await session.execute(
            text(
                f"INSERT INTO tenant_faqs "
                f"(tenant_id, question, answer, embedding, status, collection_id, expires_at) "
                f"VALUES (:t, :q, :a, CAST(:e AS halfvec), :s, :c, {expires_clause}) "
                f"RETURNING id"
            ),
            {
                "t": tenant_id,
                "q": question,
                "a": answer,
                "e": embedding_lit,
                "s": status,
                "c": coll_id,
            },
        )
    ).scalar_one()
    await session.commit()
    return fid


async def _insert_catalog(
    session: AsyncSession,
    tenant_id: UUID,
    *,
    sku: str,
    name: str,
    collection_slug: str | None = None,
) -> UUID:
    coll_id = await _collection_id(session, tenant_id, collection_slug) if collection_slug else None
    provider = MockProvider()
    embedding = await provider.create_embedding(f"{name} (sku={sku})")
    embedding_lit = "[" + ",".join(f"{x:.6f}" for x in embedding) + "]"
    cid = (
        await session.execute(
            text(
                "INSERT INTO tenant_catalogs "
                "(tenant_id, sku, name, embedding, collection_id) "
                "VALUES (:t, :s, :n, CAST(:e AS halfvec), :c) "
                "RETURNING id"
            ),
            {"t": tenant_id, "s": sku, "n": name, "e": embedding_lit, "c": coll_id},
        )
    ).scalar_one()
    await session.commit()
    return cid


@pytest.mark.asyncio
async def test_retrieve_finds_exact_match_for_seeded_faq(db_session, seeded_tenant):
    tid = seeded_tenant
    await _insert_faq(
        db_session,
        tid,
        question="¿Cuáles son los requisitos para abrir un crédito?",
        answer="Necesitas INE, comprobante de domicilio y de ingresos.",
        collection_slug="requisitos",
    )
    result = await retrieve(
        db_session,
        tid,
        "¿Cuáles son los requisitos para abrir un crédito?\nNecesitas INE, comprobante de domicilio y de ingresos.",
        "duda_general",
        provider=MockProvider(),
    )
    assert result.chunks
    assert result.chunks[0].source_type == "faq"
    assert result.chunks[0].score > 0.99


@pytest.mark.asyncio
async def test_recepcionista_cannot_retrieve_catalog(db_session, seeded_tenant):
    tid = seeded_tenant
    # Insert ONLY a catalog item — recepcionista has no 'catalog' allowed.
    await _insert_catalog(
        db_session,
        tid,
        sku="SKU-1",
        name="Modelo Dinamo U5",
        collection_slug="catalogo",
    )
    result = await retrieve(
        db_session,
        tid,
        "Modelo Dinamo U5 (sku=SKU-1)",
        "recepcionista",
        provider=MockProvider(),
        minimum_score=0.0,
    )
    assert all(c.source_type != "catalog" for c in result.chunks), result.chunks


@pytest.mark.asyncio
async def test_sales_agent_does_retrieve_catalog(db_session, seeded_tenant):
    tid = seeded_tenant
    await _insert_catalog(
        db_session,
        tid,
        sku="SKU-2",
        name="Modelo Dinamo X9",
        collection_slug="catalogo",
    )
    result = await retrieve(
        db_session,
        tid,
        "Modelo Dinamo X9 (sku=SKU-2)",
        "sales_agent",
        provider=MockProvider(),
    )
    assert any(c.source_type == "catalog" for c in result.chunks), result.chunks


@pytest.mark.asyncio
async def test_draft_faqs_dropped_unless_include_drafts(db_session, seeded_tenant):
    tid = seeded_tenant
    # Place the FAQ in a collection duda_general HAS access to so the
    # collection filter doesn't mask the publication-state filter.
    fid = await _insert_faq(
        db_session,
        tid,
        question="¿Cuánto piden de enganche para crédito?",
        answer="A partir de 10 por ciento.",
        collection_slug="credito",
        status="draft",
    )
    result = await retrieve(
        db_session,
        tid,
        "¿Cuánto piden de enganche para crédito?\nA partir de 10 por ciento.",
        "duda_general",
        provider=MockProvider(),
        minimum_score=0.0,
    )
    assert all(c.source_id != fid for c in result.chunks)

    result2 = await retrieve(
        db_session,
        tid,
        "¿Cuánto piden de enganche para crédito?\nA partir de 10 por ciento.",
        "duda_general",
        provider=MockProvider(),
        include_drafts=True,
        minimum_score=0.0,
    )
    assert any(c.source_id == fid for c in result2.chunks)


@pytest.mark.asyncio
async def test_expired_faqs_are_dropped(db_session, seeded_tenant):
    tid = seeded_tenant
    fid = await _insert_faq(
        db_session,
        tid,
        question="¿Hay descuento navideño?",
        answer="Sólo en diciembre.",
        collection_slug="promociones",
        status="published",
        expires_at_sql="now() - interval '1 day'",
    )
    result = await retrieve(
        db_session,
        tid,
        "¿Hay descuento navideño?\nSólo en diciembre.",
        "sales_agent",
        provider=MockProvider(),
        minimum_score=0.0,
    )
    assert all(c.source_id != fid for c in result.chunks), result.chunks


@pytest.mark.asyncio
async def test_min_score_floor_drops_low_similarity(db_session, seeded_tenant):
    tid = seeded_tenant
    await _insert_faq(
        db_session,
        tid,
        question="¿Qué hora es?",
        answer="Cualquier momento.",
        collection_slug="dudas_basicas",
    )
    # Query is wildly unrelated — MockProvider scores will be < 0.99 due to
    # different SHA inputs but typically still well above 0.5 because of
    # uniform random vectors. We crank min_score very high to force a drop.
    result = await retrieve(
        db_session,
        tid,
        "Lorem ipsum dolor sit amet xyz123 unrelated topic",
        "duda_general",
        provider=MockProvider(),
        minimum_score=0.9999,
    )
    # The exact-match-only test uses score > 0.99; an unrelated query should
    # not exceed 0.9999 similarity.
    assert all(c.score >= 0.9999 for c in result.chunks)
