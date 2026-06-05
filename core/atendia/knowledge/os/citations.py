from __future__ import annotations

from atendia.knowledge.os.schemas import (
    EvidenceSnippet,
    KnowledgeCitation,
    KnowledgeRecord,
    SourceCard,
)


def citation_from_record(record: KnowledgeRecord) -> KnowledgeCitation:
    snippet = record.chunk.chunk_text[:500]
    return KnowledgeCitation(
        source_id=record.source.id,
        item_id=record.item.id,
        chunk_id=record.chunk.id,
        source_name=record.source.name,
        title=record.item.title,
        snippet=snippet,
        score=record.score,
        source_type=record.source.type,
        content_type=record.source.content_type,
        metadata={
            **record.source.metadata,
            **record.item.metadata,
            **record.chunk.metadata,
        },
    )


def snippet_from_record(record: KnowledgeRecord) -> EvidenceSnippet:
    return EvidenceSnippet(
        chunk_id=record.chunk.id,
        text=record.chunk.chunk_text[:700],
        score=record.score,
        title=record.item.title,
        source_name=record.source.name,
        metadata=record.chunk.metadata,
    )


def source_cards_from_records(records: list[KnowledgeRecord]) -> list[SourceCard]:
    cards: dict[str, SourceCard] = {}
    for record in records:
        key = str(record.source.id)
        cards.setdefault(
            key,
            SourceCard(
                source_id=record.source.id,
                name=record.source.name,
                type=record.source.type,
                content_type=record.source.content_type,
                status=record.source.status,
                priority=record.source.priority,
                metadata=record.source.metadata,
            ),
        )
    return list(cards.values())
