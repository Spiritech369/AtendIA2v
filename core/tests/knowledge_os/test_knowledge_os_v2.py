from __future__ import annotations

from uuid import uuid4

import pytest

from atendia.agent_runtime.context_builder import ContextBuilder
from atendia.agent_runtime.schemas import TurnInput
from atendia.api import knowledge_routes
from atendia.knowledge.os import InMemoryKnowledgeRepository
from atendia.knowledge.os.ingestion import FAQSeed, KnowledgeIngestionService
from atendia.knowledge.os.legacy_adapters import evidence_from_legacy_rag_chunks
from atendia.knowledge.os.retrieval import KnowledgeRetrievalService
from atendia.knowledge.os.schemas import EvidencePack, KnowledgeCitation
from atendia.tools.rag.retriever import RetrievedChunk


@pytest.mark.asyncio
async def test_create_source_item_chunk_from_manual_text():
    tenant_id = uuid4()
    repo = InMemoryKnowledgeRepository()
    ingestion = KnowledgeIngestionService(repo)

    source, items, chunks = await ingestion.ingest_manual_text(
        tenant_id=tenant_id,
        name="Store policy",
        content="Returns are accepted within seven days with the original receipt.",
        content_type="policy",
    )

    assert source.tenant_id == tenant_id
    assert source.type == "manual"
    assert source.status == "active"
    assert items[0].source_id == source.id
    assert chunks[0].item_id == items[0].id
    assert "seven days" in chunks[0].chunk_text


@pytest.mark.asyncio
async def test_retrieval_respects_tenant_isolation_and_returns_citations():
    tenant_a = uuid4()
    tenant_b = uuid4()
    repo = InMemoryKnowledgeRepository()
    ingestion = KnowledgeIngestionService(repo)
    retrieval = KnowledgeRetrievalService(repo)

    await ingestion.ingest_manual_text(
        tenant_id=tenant_a,
        name="Tenant A support",
        content="Appointments are available Monday morning.",
        content_type="appointment_rules",
    )
    await ingestion.ingest_manual_text(
        tenant_id=tenant_b,
        name="Tenant B support",
        content="Appointments are available Friday evening.",
        content_type="appointment_rules",
    )

    evidence = await retrieval.retrieve(
        tenant_id=tenant_a,
        query="appointments Monday",
    )

    assert evidence.answerable is True
    assert evidence.citations
    assert evidence.citations[0].source_name == "Tenant A support"
    assert "Friday" not in " ".join(snippet.text for snippet in evidence.snippets)


@pytest.mark.asyncio
async def test_retrieval_no_match_is_not_answerable():
    tenant_id = uuid4()
    repo = InMemoryKnowledgeRepository()
    ingestion = KnowledgeIngestionService(repo)
    retrieval = KnowledgeRetrievalService(repo)

    await ingestion.ingest_manual_text(
        tenant_id=tenant_id,
        name="Policy",
        content="Service hours are Monday to Thursday.",
    )

    evidence = await retrieval.retrieve(tenant_id=tenant_id, query="warranty transfer")

    assert evidence.answerable is False
    assert evidence.citations == []
    assert evidence.missing_info


@pytest.mark.asyncio
async def test_context_builder_includes_knowledge_snippets_without_session():
    tenant_id = uuid4()
    conversation_id = uuid4()
    repo = InMemoryKnowledgeRepository()
    ingestion = KnowledgeIngestionService(repo)
    retrieval = KnowledgeRetrievalService(repo)
    await ingestion.ingest_faqs(
        tenant_id=tenant_id,
        name="FAQ",
        faqs=[
            FAQSeed(
                question="What are support hours?",
                answer="Support hours are Monday morning.",
            )
        ],
    )

    context = await ContextBuilder(knowledge_provider=retrieval).build(
        TurnInput(
            tenant_id=str(tenant_id),
            conversation_id=str(conversation_id),
            inbound_text="support hours Monday",
        )
    )

    assert context.knowledge_citations
    assert context.knowledge_citations[0].title == "What are support hours?"
    assert context.metadata["knowledge"]["answerable"] is True


@pytest.mark.asyncio
async def test_context_builder_does_not_fail_when_knowledge_is_empty():
    context = await ContextBuilder().build(
        TurnInput(
            tenant_id=str(uuid4()),
            conversation_id=str(uuid4()),
            inbound_text="hello",
        )
    )

    assert context.knowledge_citations == []
    assert context.metadata["knowledge"]["enabled"] is False


def test_knowledge_os_does_not_break_legacy_knowledge_routes_import():
    assert hasattr(knowledge_routes, "router")


def test_evidence_pack_has_source_cards_and_citations_shape():
    citation = KnowledgeCitation(
        source_id=uuid4(),
        item_id=uuid4(),
        chunk_id=uuid4(),
        source_name="Manual",
        title="Policy",
        snippet="Policy snippet",
        score=0.9,
        source_type="manual",
        content_type="policy",
    )
    pack = EvidencePack(
        answerable=True,
        confidence=0.9,
        citations=[citation],
    )

    assert pack.conflicts == []
    assert pack.citations[0].snippet == "Policy snippet"


def test_legacy_rag_chunks_convert_to_knowledge_os_evidence_shape():
    source_id = uuid4()
    evidence = evidence_from_legacy_rag_chunks(
        [
            RetrievedChunk(
                source_type="faq",
                source_id=source_id,
                text="Legacy FAQ answer.",
                score=0.91,
            )
        ]
    )

    assert evidence.answerable is True
    assert evidence.citations[0].source_id == source_id
    assert evidence.source_cards[0].metadata["legacy_rag"] is True
