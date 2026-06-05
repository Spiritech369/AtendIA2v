from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.db.models.knowledge_document import KnowledgeChunk as LegacyKnowledgeChunk
from atendia.db.models.knowledge_document import KnowledgeDocument
from atendia.db.models.tenant_config import TenantCatalogItem, TenantFAQ
from atendia.knowledge.os.citations import (
    citation_from_record,
    snippet_from_record,
    source_cards_from_records,
)
from atendia.knowledge.os.schemas import (
    EvidencePack,
    KnowledgeChunk,
    KnowledgeItem,
    KnowledgeRecord,
    KnowledgeSource,
)
from atendia.knowledge.os.service import (
    SqlAlchemyKnowledgeRepository,
    normalize_match_text,
    score_text_match,
)

_ACTIVE_LEGACY_DOCUMENT_STATUSES = {"indexed", "ready", "active", "published", "embedded"}
_ACTIVE_LEGACY_CHUNK_STATUSES = {"embedded", "ready", "active", "published", "indexed"}
_KNOWLEDGE_OS_CONTENT_TYPES = {
    "faq",
    "policy",
    "credit_policy",
    "pricing",
    "catalog",
    "services",
    "appointment_rules",
    "document_rules",
    "location_hours",
    "inventory_color_policy",
    "general",
}


class LegacyKnowledgeAdapter:
    """Read legacy KB tables as Knowledge OS records without copying data."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def search_records(
        self,
        *,
        tenant_id: UUID,
        query: str,
        agent_id: UUID | None = None,
        source_ids: set[UUID] | None = None,
        limit: int = 8,
    ) -> list[KnowledgeRecord]:
        del agent_id
        records = [
            *await self._faq_records(
                tenant_id=tenant_id,
                query=query,
                source_ids=source_ids,
            ),
            *await self._catalog_records(
                tenant_id=tenant_id,
                query=query,
                source_ids=source_ids,
            ),
            *await self._document_records(
                tenant_id=tenant_id,
                query=query,
                source_ids=source_ids,
            ),
        ]
        records.sort(key=lambda record: (-record.score, -record.source.priority, record.item.title))
        return records[:limit]

    async def _faq_records(
        self,
        *,
        tenant_id: UUID,
        query: str,
        source_ids: set[UUID] | None,
    ) -> list[KnowledgeRecord]:
        rows = (
            (
                await self._session.execute(
                    select(TenantFAQ).where(
                        TenantFAQ.tenant_id == tenant_id,
                        TenantFAQ.status == "published",
                    )
                )
            )
            .scalars()
            .all()
        )
        records: list[KnowledgeRecord] = []
        for row in rows:
            if source_ids and row.id not in source_ids:
                continue
            text = f"{row.question}\n{row.answer}"
            score = score_text_match(
                query,
                text,
                content_type="faq",
                title=row.question,
                source_name=row.question,
            )
            if score <= 0:
                continue
            source = KnowledgeSource(
                id=row.id,
                tenant_id=tenant_id,
                name=row.question,
                type="faq",
                content_type="faq",
                status="active",
                priority=row.priority or 0,
                metadata={
                    "source_kind": "legacy",
                    "adapted": True,
                    "legacy_table": "tenant_faqs",
                    "tags": list(row.tags or []),
                    "status": row.status,
                },
            )
            item = KnowledgeItem(
                id=row.id,
                tenant_id=tenant_id,
                source_id=row.id,
                title=row.question,
                content=text,
                structured_data={"question": row.question, "answer": row.answer},
                metadata={"legacy_table": "tenant_faqs"},
            )
            chunk = KnowledgeChunk(
                id=row.id,
                tenant_id=tenant_id,
                source_id=row.id,
                item_id=row.id,
                chunk_text=text,
                chunk_index=0,
                metadata={"legacy_table": "tenant_faqs"},
            )
            records.append(KnowledgeRecord(source=source, item=item, chunk=chunk, score=score))
        return records

    async def _catalog_records(
        self,
        *,
        tenant_id: UUID,
        query: str,
        source_ids: set[UUID] | None,
    ) -> list[KnowledgeRecord]:
        rows = (
            (
                await self._session.execute(
                    select(TenantCatalogItem).where(
                        TenantCatalogItem.tenant_id == tenant_id,
                        TenantCatalogItem.active.is_(True),
                        TenantCatalogItem.status == "published",
                    )
                )
            )
            .scalars()
            .all()
        )
        records: list[KnowledgeRecord] = []
        for row in rows:
            if source_ids and row.id not in source_ids:
                continue
            text = _catalog_text(row)
            score = score_text_match(
                query,
                text,
                content_type="catalog",
                title=row.name,
                source_name=row.name,
            )
            if score <= 0:
                continue
            source = KnowledgeSource(
                id=row.id,
                tenant_id=tenant_id,
                name=row.name,
                type="table",
                content_type="catalog",
                status="active",
                priority=row.priority or 0,
                metadata={
                    "source_kind": "legacy",
                    "adapted": True,
                    "legacy_table": "tenant_catalogs",
                    "sku": row.sku,
                    "category": row.category,
                    "status": row.status,
                },
            )
            item = KnowledgeItem(
                id=row.id,
                tenant_id=tenant_id,
                source_id=row.id,
                title=row.name,
                content=text,
                structured_data={
                    "sku": row.sku,
                    "name": row.name,
                    "attrs": dict(row.attrs or {}),
                    "price_cents": row.price_cents,
                    "stock_status": row.stock_status,
                    "payment_plans": list(row.payment_plans or []),
                },
                metadata={"legacy_table": "tenant_catalogs"},
            )
            chunk = KnowledgeChunk(
                id=row.id,
                tenant_id=tenant_id,
                source_id=row.id,
                item_id=row.id,
                chunk_text=text,
                chunk_index=0,
                metadata={"legacy_table": "tenant_catalogs", "sku": row.sku},
            )
            records.append(KnowledgeRecord(source=source, item=item, chunk=chunk, score=score))
        return records

    async def _document_records(
        self,
        *,
        tenant_id: UUID,
        query: str,
        source_ids: set[UUID] | None,
    ) -> list[KnowledgeRecord]:
        rows = (
            await self._session.execute(
                select(LegacyKnowledgeChunk, KnowledgeDocument)
                .join(KnowledgeDocument, LegacyKnowledgeChunk.document_id == KnowledgeDocument.id)
                .where(
                    LegacyKnowledgeChunk.tenant_id == tenant_id,
                    LegacyKnowledgeChunk.chunk_status.in_(_ACTIVE_LEGACY_CHUNK_STATUSES),
                    KnowledgeDocument.status.in_(_ACTIVE_LEGACY_DOCUMENT_STATUSES),
                )
            )
        ).all()
        records: list[KnowledgeRecord] = []
        for chunk_row, document_row in rows:
            if source_ids and not {chunk_row.id, document_row.id}.intersection(source_ids):
                continue
            content_type = _knowledge_content_type(
                f"{document_row.category or ''} {document_row.filename}"
            )
            score = score_text_match(
                query,
                chunk_row.text,
                content_type=content_type,
                title=chunk_row.heading or document_row.filename,
                source_name=document_row.filename,
            )
            if score <= 0:
                continue
            source = KnowledgeSource(
                id=document_row.id,
                tenant_id=tenant_id,
                name=document_row.filename,
                type="file",
                content_type=content_type,
                status="active",
                priority=document_row.priority or 0,
                metadata={
                    "source_kind": "legacy",
                    "adapted": True,
                    "legacy_table": "knowledge_documents",
                    "status": document_row.status,
                    "category": document_row.category,
                },
            )
            item = KnowledgeItem(
                id=chunk_row.id,
                tenant_id=tenant_id,
                source_id=document_row.id,
                title=chunk_row.heading or document_row.filename,
                content=chunk_row.text,
                metadata={
                    "legacy_table": "knowledge_chunks",
                    "document_id": str(document_row.id),
                },
            )
            chunk = KnowledgeChunk(
                id=chunk_row.id,
                tenant_id=tenant_id,
                source_id=document_row.id,
                item_id=chunk_row.id,
                chunk_text=chunk_row.text,
                chunk_index=chunk_row.chunk_index,
                metadata={
                    "legacy_table": "knowledge_chunks",
                    "document_id": str(document_row.id),
                    "page": chunk_row.page,
                    "heading": chunk_row.heading,
                    "section": chunk_row.section,
                },
            )
            records.append(KnowledgeRecord(source=source, item=item, chunk=chunk, score=score))
        return records


class UnifiedKnowledgeProvider:
    """Retrieve native Knowledge OS records first, then legacy adapted records."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        min_score: float = 0.2,
        top_k: int = 5,
        include_native: bool = True,
        include_legacy: bool = True,
    ) -> None:
        self._session = session
        self._min_score = min_score
        self._top_k = top_k
        self._include_native = include_native
        self._include_legacy = include_legacy

    async def retrieve(
        self,
        *,
        tenant_id: UUID | str,
        query: str,
        agent_id: UUID | str | None = None,
        source_ids: list[UUID | str] | None = None,
        top_k: int | None = None,
    ) -> EvidencePack:
        tenant_uuid = _coerce_uuid(tenant_id)
        agent_uuid = _coerce_uuid(agent_id) if agent_id is not None else None
        selected = {_coerce_uuid(value) for value in source_ids} if source_ids else None
        limit = top_k or self._top_k
        records: list[KnowledgeRecord] = []
        if self._include_native:
            records.extend(
                await SqlAlchemyKnowledgeRepository(self._session).search_records(
                    tenant_id=tenant_uuid,
                    query=query,
                    agent_id=agent_uuid,
                    source_ids=selected,
                    limit=limit,
                )
            )
        if self._include_legacy:
            records.extend(
                await LegacyKnowledgeAdapter(self._session).search_records(
                    tenant_id=tenant_uuid,
                    query=query,
                    agent_id=agent_uuid,
                    source_ids=selected,
                    limit=limit,
                )
            )
        records = [
            record for record in records if record.score >= self._min_score
        ]
        records.sort(
            key=lambda record: (-record.score, _source_kind_rank(record), record.item.title)
        )
        records = _dedupe_records(records)[:limit]
        citations = [citation_from_record(record) for record in records]
        evidence = EvidencePack(
            answerable=bool(records),
            confidence=max((record.score for record in records), default=0.0),
            snippets=[snippet_from_record(record) for record in records],
            citations=citations,
            source_cards=source_cards_from_records(records),
            conflicts=[],
            missing_info=None if records else "No matching Knowledge OS snippets found.",
        )
        if self._include_native:
            log_id = await SqlAlchemyKnowledgeRepository(self._session).log_retrieval(
                tenant_id=tenant_uuid,
                agent_id=agent_uuid,
                query=query,
                evidence=evidence,
            )
            return evidence.model_copy(update={"retrieval_log_id": log_id})
        return evidence


def evidence_from_legacy_rag_chunks(
    chunks: list[Any],
    *,
    missing_info: str | None = None,
) -> EvidencePack:
    records: list[KnowledgeRecord] = []
    for index, chunk in enumerate(chunks):
        source_id = _coerce_uuid(getattr(chunk, "document_id", None) or chunk.source_id)
        chunk_id = _coerce_uuid(chunk.source_id)
        source_type = str(getattr(chunk, "source_type", "document") or "document")
        if source_type == "catalog":
            content_type = "catalog"
        elif source_type == "faq":
            content_type = "faq"
        else:
            content_type = "general"
        text = str(getattr(chunk, "text", "") or "")
        source = KnowledgeSource(
            id=source_id,
            tenant_id=source_id,
            name=_legacy_rag_source_name(chunk),
            type=_legacy_source_type(source_type),
            content_type=content_type,
            status="active",
            metadata={
                "source_kind": "legacy",
                "adapted": True,
                "legacy_rag": True,
                "source_type": source_type,
                "collection": getattr(chunk, "collection", None),
            },
        )
        item = KnowledgeItem(
            id=chunk_id,
            tenant_id=source_id,
            source_id=source_id,
            title=getattr(chunk, "heading", None) or source.name,
            content=text,
        )
        records.append(
            KnowledgeRecord(
                source=source,
                item=item,
                chunk=KnowledgeChunk(
                    id=chunk_id,
                    tenant_id=source_id,
                    source_id=source_id,
                    item_id=chunk_id,
                    chunk_text=text,
                    chunk_index=index,
                    metadata={
                        "page": getattr(chunk, "page", None),
                        "heading": getattr(chunk, "heading", None),
                        "document_id": str(getattr(chunk, "document_id", "") or ""),
                        "legacy_rag": True,
                    },
                ),
                score=float(getattr(chunk, "score", 0.0) or 0.0),
            )
        )
    records.sort(key=lambda record: -record.score)
    return EvidencePack(
        answerable=bool(records),
        confidence=max((record.score for record in records), default=0.0),
        snippets=[snippet_from_record(record) for record in records],
        citations=[citation_from_record(record) for record in records],
        source_cards=source_cards_from_records(records),
        missing_info=None if records else missing_info,
    )


def _catalog_text(row: TenantCatalogItem) -> str:
    parts = [
        row.name,
        f"sku: {row.sku}",
        f"category: {row.category}" if row.category else "",
        f"stock: {row.stock_status}" if row.stock_status else "",
        f"price_cents: {row.price_cents}" if row.price_cents is not None else "",
    ]
    attrs = row.attrs or {}
    for key, value in attrs.items():
        parts.append(f"{key}: {value}")
    if row.payment_plans:
        parts.append(f"payment_plans: {row.payment_plans}")
    if row.tags:
        parts.append(f"tags: {row.tags}")
    return "\n".join(part for part in parts if part)


def _knowledge_content_type(value: str | None) -> str:
    normalized = normalize_match_text(value or "general")
    if any(term in normalized for term in ("catalogo", "catalog")):
        return "catalog"
    if any(term in normalized for term in ("credito", "creditos", "financiamiento", "buro")):
        return "credit_policy"
    if any(
        term in normalized
        for term in ("documento", "documentos", "requisito", "requisitos", "ine")
    ):
        return "document_rules"
    if any(term in normalized for term in ("ubicacion", "direccion", "horario", "sucursal")):
        return "location_hours"
    if any(term in normalized for term in ("cita", "agenda", "visita")):
        return "appointment_rules"
    if any(term in normalized for term in ("inventario", "color", "stock")):
        return "inventory_color_policy"
    return normalized if normalized in _KNOWLEDGE_OS_CONTENT_TYPES else "general"


def _coerce_uuid(value: UUID | str | Any) -> UUID:
    if isinstance(value, UUID):
        return value
    return UUID(str(value))


def _source_kind_rank(record: KnowledgeRecord) -> int:
    return 0 if record.source.metadata.get("source_kind") != "legacy" else 1


def _dedupe_records(records: list[KnowledgeRecord]) -> list[KnowledgeRecord]:
    seen: set[tuple[str, str]] = set()
    out: list[KnowledgeRecord] = []
    for record in records:
        key = (str(record.source.id), str(record.chunk.id))
        if key in seen:
            continue
        seen.add(key)
        out.append(record)
    return out


def _legacy_rag_source_name(chunk: Any) -> str:
    source_type = getattr(chunk, "source_type", "document")
    heading = getattr(chunk, "heading", None)
    if heading:
        return str(heading)
    return f"Legacy {source_type}"


def _legacy_source_type(source_type: str) -> str:
    if source_type == "catalog":
        return "table"
    if source_type == "faq":
        return "faq"
    return "file"
