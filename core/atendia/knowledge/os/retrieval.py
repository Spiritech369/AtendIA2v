from __future__ import annotations

from typing import Any
from uuid import UUID

from atendia.knowledge.os.citations import (
    citation_from_record,
    snippet_from_record,
    source_cards_from_records,
)
from atendia.knowledge.os.schemas import EvidencePack
from atendia.knowledge.os.service import KnowledgeRepository


class KnowledgeRetrievalService:
    def __init__(
        self,
        repository: KnowledgeRepository,
        *,
        min_score: float = 0.2,
        top_k: int = 5,
    ) -> None:
        self._repository = repository
        self._min_score = min_score
        self._top_k = top_k

    async def retrieve(
        self,
        *,
        tenant_id: UUID | str,
        query: str,
        agent_id: UUID | str | None = None,
        source_ids: list[UUID | str] | None = None,
        top_k: int | None = None,
    ) -> EvidencePack:
        resolved_tenant_id = _coerce_uuid(tenant_id)
        resolved_agent_id = _coerce_uuid(agent_id) if agent_id is not None else None
        resolved_source_ids = (
            {_coerce_uuid(source_id) for source_id in source_ids}
            if source_ids
            else None
        )
        limit = top_k or self._top_k
        records = await self._repository.search_records(
            tenant_id=resolved_tenant_id,
            query=query,
            agent_id=resolved_agent_id,
            source_ids=resolved_source_ids,
            limit=limit,
        )
        records = [record for record in records if record.score >= self._min_score][:limit]
        citations = [citation_from_record(record) for record in records]
        confidence = max((record.score for record in records), default=0.0)
        evidence = EvidencePack(
            answerable=bool(records),
            confidence=confidence,
            snippets=[snippet_from_record(record) for record in records],
            citations=citations,
            source_cards=source_cards_from_records(records),
            conflicts=[],
            missing_info=None if records else "No matching Knowledge OS snippets found.",
        )
        log_id = await self._repository.log_retrieval(
            tenant_id=resolved_tenant_id,
            agent_id=resolved_agent_id,
            query=query,
            evidence=evidence,
        )
        return evidence.model_copy(update={"retrieval_log_id": log_id})


def _coerce_uuid(value: UUID | str | Any) -> UUID:
    if isinstance(value, UUID):
        return value
    return UUID(str(value))
