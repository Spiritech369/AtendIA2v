"""HTTP-level smoke for POST /api/v1/knowledge/test-query.

The keystone of the KB module: confirms the endpoint round-trips the
full Phase 2 pipeline (retriever → prompt builder → synthesizer) and
returns the structured response shape the frontend depends on.

Uses MockProvider implicitly via KB_PROVIDER=mock (or by leaving
OPENAI_API_KEY empty in the test environment) so this runs offline.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from atendia.config import get_settings
from atendia.scripts.seed_knowledge_defaults import seed_for_tenant
from atendia.tools.rag import get_provider
from atendia.tools.rag.mock_provider import MockProvider


@pytest.fixture(autouse=True)
def _force_mock_provider(monkeypatch):
    """Pin KB_PROVIDER=mock for these tests so the synthesizer's mode
    will be 'mock' and we don't touch OpenAI."""
    monkeypatch.setenv("ATENDIA_V2_KB_PROVIDER", "mock")
    get_settings.cache_clear()
    get_provider.cache_clear()
    yield
    get_settings.cache_clear()
    get_provider.cache_clear()


async def _seed(tenant_id):
    engine = create_async_engine(get_settings().database_url)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with Session() as session:
        await seed_for_tenant(session, tenant_id)
        # Insert one FAQ in 'requisitos' so duda_general has something to retrieve.
        provider = MockProvider()
        text_body = "INE, comprobante de domicilio y de ingresos."
        embedding = await provider.create_embedding(f"¿Requisitos?\n{text_body}")
        embedding_lit = "[" + ",".join(f"{x:.6f}" for x in embedding) + "]"
        coll_id = (
            await session.execute(
                text("SELECT id FROM kb_collections WHERE tenant_id=:t AND slug='requisitos'"),
                {"t": tenant_id},
            )
        ).scalar_one()
        await session.execute(
            text(
                "INSERT INTO tenant_faqs "
                "(tenant_id, question, answer, embedding, status, collection_id) "
                "VALUES (:t, :q, :a, CAST(:e AS halfvec), 'published', :c)"
            ),
            {"t": tenant_id, "q": "¿Requisitos?", "a": text_body, "e": embedding_lit, "c": coll_id},
        )
        await session.commit()
    await engine.dispose()


@pytest.mark.asyncio
async def test_test_query_returns_full_structured_shape(client_tenant_admin):
    await _seed(client_tenant_admin.tenant_id)

    resp = client_tenant_admin.post(
        "/api/v1/knowledge/test-query",
        json={
            "query": "¿Requisitos?\nINE, comprobante de domicilio y de ingresos.",
            "agent": "duda_general",
            "minimum_score": 0.0,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # Top-level keys per the design's TestQueryResponse.
    assert set(body.keys()) >= {
        "query",
        "agent",
        "retrieved_chunks",
        "prompt",
        "answer",
        "confidence",
        "action",
        "risks",
        "citations",
        "mode",
    }
    assert body["agent"] == "duda_general"
    assert body["mode"] == "mock"
    assert isinstance(body["retrieved_chunks"], list)
    # The seeded FAQ should match.
    assert any(c["source_type"] == "faq" for c in body["retrieved_chunks"])


@pytest.mark.asyncio
async def test_test_query_include_drafts_requires_admin(client_operator):
    """Operator (non-admin) cannot pass include_drafts=True."""
    resp = client_operator.post(
        "/api/v1/knowledge/test-query",
        json={
            "query": "x",
            "agent": "duda_general",
            "include_drafts": True,
        },
    )
    assert resp.status_code == 403, resp.text
