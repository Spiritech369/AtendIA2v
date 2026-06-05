from __future__ import annotations

from uuid import UUID, uuid4

import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from atendia.config import get_settings
from atendia.knowledge.os import UnifiedKnowledgeProvider
from atendia.knowledge.os.service import score_text_match


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine(get_settings().database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db:
        yield db
        await db.rollback()
    await engine.dispose()


async def _tenant_pair(session) -> tuple[UUID, UUID]:
    tenant_a = (
        await session.execute(
            text("INSERT INTO tenants (name) VALUES (:n) RETURNING id"),
            {"n": f"knowledge_legacy_a_{uuid4().hex[:8]}"},
        )
    ).scalar_one()
    tenant_b = (
        await session.execute(
            text("INSERT INTO tenants (name) VALUES (:n) RETURNING id"),
            {"n": f"knowledge_legacy_b_{uuid4().hex[:8]}"},
        )
    ).scalar_one()
    return tenant_a, tenant_b


async def test_faq_adapter_returns_knowledge_evidence_tenant_scoped(session):
    tenant_a, tenant_b = await _tenant_pair(session)
    await session.execute(
        text(
            "INSERT INTO tenant_faqs (tenant_id, question, answer, tags, status) "
            "VALUES (:tenant_id, :question, :answer, CAST('[]' AS jsonb), 'published')"
        ),
        {
            "tenant_id": tenant_a,
            "question": "Warranty terms",
            "answer": "Own tenant warranty covers Monday repairs.",
        },
    )
    await session.execute(
        text(
            "INSERT INTO tenant_faqs (tenant_id, question, answer, tags, status) "
            "VALUES (:tenant_id, :question, :answer, CAST('[]' AS jsonb), 'published')"
        ),
        {
            "tenant_id": tenant_b,
            "question": "Warranty terms",
            "answer": "Other tenant warranty covers Friday repairs.",
        },
    )
    await session.flush()

    evidence = await UnifiedKnowledgeProvider(session).retrieve(
        tenant_id=tenant_a,
        query="warranty repairs",
    )

    snippets = " ".join(citation.snippet for citation in evidence.citations)
    assert "Own tenant warranty" in snippets
    assert "Other tenant warranty" not in snippets
    assert any(
        citation.metadata["legacy_table"] == "tenant_faqs"
        for citation in evidence.citations
    )
    assert all(card.metadata.get("adapted") is True for card in evidence.source_cards)


async def test_catalog_adapter_returns_knowledge_evidence_tenant_scoped(session):
    tenant_a, tenant_b = await _tenant_pair(session)
    await session.execute(
        text(
            "INSERT INTO tenant_catalogs (tenant_id, sku, name, attrs, active, status) "
            "VALUES (:tenant_id, 'OWN-001', 'Quartz Own Catalog', "
            "CAST('{\"engine\":\"125cc\"}' AS jsonb), true, 'published')"
        ),
        {"tenant_id": tenant_a},
    )
    await session.execute(
        text(
            "INSERT INTO tenant_catalogs (tenant_id, sku, name, attrs, active, status) "
            "VALUES (:tenant_id, 'OTHER-001', 'Quartz Other Catalog', "
            "CAST('{\"engine\":\"999cc\"}' AS jsonb), true, 'published')"
        ),
        {"tenant_id": tenant_b},
    )
    await session.flush()

    evidence = await UnifiedKnowledgeProvider(session).retrieve(
        tenant_id=tenant_a,
        query="Quartz Catalog engine",
    )

    snippets = " ".join(citation.snippet for citation in evidence.citations)
    assert "Quartz Own Catalog" in snippets
    assert "Quartz Other Catalog" not in snippets
    assert any(
        citation.metadata["legacy_table"] == "tenant_catalogs"
        for citation in evidence.citations
    )


async def test_document_chunk_adapter_returns_knowledge_evidence_tenant_scoped(
    session,
):
    tenant_a, tenant_b = await _tenant_pair(session)
    document_a = (
        await session.execute(
            text(
                "INSERT INTO knowledge_documents "
                "(tenant_id, filename, storage_path, category, status, fragment_count) "
                "VALUES (:tenant_id, 'own-policy.txt', 'own/policy.txt', 'policy', "
                "'indexed', 1) RETURNING id"
            ),
            {"tenant_id": tenant_a},
        )
    ).scalar_one()
    document_b = (
        await session.execute(
            text(
                "INSERT INTO knowledge_documents "
                "(tenant_id, filename, storage_path, category, status, fragment_count) "
                "VALUES (:tenant_id, 'other-policy.txt', 'other/policy.txt', 'policy', "
                "'indexed', 1) RETURNING id"
            ),
            {"tenant_id": tenant_b},
        )
    ).scalar_one()
    await session.execute(
        text(
            "INSERT INTO knowledge_chunks "
            "(tenant_id, document_id, chunk_index, text, chunk_status) "
            "VALUES (:tenant_id, :document_id, 0, :text, 'embedded')"
        ),
        {
            "tenant_id": tenant_a,
            "document_id": document_a,
            "text": "Own tenant document requires original receipt validation.",
        },
    )
    await session.execute(
        text(
            "INSERT INTO knowledge_chunks "
            "(tenant_id, document_id, chunk_index, text, chunk_status) "
            "VALUES (:tenant_id, :document_id, 0, :text, 'embedded')"
        ),
        {
            "tenant_id": tenant_b,
            "document_id": document_b,
            "text": "Other tenant document requires passport validation.",
        },
    )
    await session.flush()

    evidence = await UnifiedKnowledgeProvider(session).retrieve(
        tenant_id=tenant_a,
        query="document receipt validation",
    )

    snippets = " ".join(citation.snippet for citation in evidence.citations)
    assert "Own tenant document" in snippets
    assert "Other tenant document" not in snippets
    assert any(citation.source_id == document_a for citation in evidence.citations)
    assert any(
        citation.metadata["legacy_table"] == "knowledge_chunks"
        for citation in evidence.citations
    )


async def test_text_match_normalizes_accents_punctuation_and_catalog_titles(session):
    tenant_a, _tenant_b = await _tenant_pair(session)
    await session.execute(
        text(
            "INSERT INTO tenant_catalogs "
            "(tenant_id, sku, name, attrs, active, status, price_cents) "
            "VALUES (:tenant_id, 'ADV-150', 'Adventure Elite 150 CC', "
            "CAST('{\"aliases\":[\"Adventure\"],\"engine\":\"150cc\"}' AS jsonb), "
            "true, 'published', 4999900)"
        ),
        {"tenant_id": tenant_a},
    )
    await session.flush()

    evidence = await UnifiedKnowledgeProvider(session).retrieve(
        tenant_id=tenant_a,
        query="¿Cuánto cuesta la Adventure?",
    )

    assert evidence.answerable is True
    assert evidence.citations[0].title == "Adventure Elite 150 CC"
    assert evidence.citations[0].content_type == "catalog"


async def test_short_reply_without_context_does_not_create_weak_citations(session):
    tenant_a, _tenant_b = await _tenant_pair(session)
    await session.execute(
        text(
            "INSERT INTO tenant_faqs (tenant_id, question, answer, tags, status) "
            "VALUES (:tenant_id, 'Credit answer', 'Sí podemos revisar crédito.', "
            "CAST('[]' AS jsonb), 'published')"
        ),
        {"tenant_id": tenant_a},
    )
    await session.flush()

    evidence = await UnifiedKnowledgeProvider(session).retrieve(
        tenant_id=tenant_a,
        query="Sí",
    )

    assert evidence.answerable is False
    assert evidence.citations == []


def test_content_type_boost_prefers_intended_policy_category():
    location_score = score_text_match(
        "¿Dónde es la ubicación?",
        "No hay dirección pública validada en Knowledge OS.",
        content_type="location_hours",
        title="Ubicación y horarios",
    )
    generic_score = score_text_match(
        "¿Dónde es la ubicación?",
        "No hay dirección pública validada en Knowledge OS.",
        content_type="general",
        title="Ubicación y horarios",
    )

    assert location_score > generic_score
