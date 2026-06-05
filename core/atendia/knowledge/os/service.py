from __future__ import annotations

import re
import unicodedata
from typing import Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.db.models.knowledge_os import (
    KnowledgeItem as KnowledgeItemRow,
)
from atendia.db.models.knowledge_os import (
    KnowledgeOSChunk as KnowledgeChunkRow,
)
from atendia.db.models.knowledge_os import (
    KnowledgeRetrievalLog as KnowledgeRetrievalLogRow,
)
from atendia.db.models.knowledge_os import (
    KnowledgeSource as KnowledgeSourceRow,
)
from atendia.knowledge.os.schemas import (
    EvidencePack,
    KnowledgeChunk,
    KnowledgeItem,
    KnowledgeRecord,
    KnowledgeSource,
)


class KnowledgeRepository(Protocol):
    async def create_source(self, source: KnowledgeSource) -> KnowledgeSource: ...
    async def create_item(self, item: KnowledgeItem) -> KnowledgeItem: ...
    async def create_chunk(self, chunk: KnowledgeChunk) -> KnowledgeChunk: ...
    async def search_records(
        self,
        *,
        tenant_id: UUID,
        query: str,
        agent_id: UUID | None = None,
        source_ids: set[UUID] | None = None,
        limit: int = 8,
    ) -> list[KnowledgeRecord]: ...
    async def log_retrieval(
        self,
        *,
        tenant_id: UUID,
        agent_id: UUID | None,
        query: str,
        evidence: EvidencePack,
    ) -> UUID | None: ...


class InMemoryKnowledgeRepository:
    def __init__(self) -> None:
        self.sources: dict[UUID, KnowledgeSource] = {}
        self.items: dict[UUID, KnowledgeItem] = {}
        self.chunks: dict[UUID, KnowledgeChunk] = {}
        self.logs: list[dict] = []

    async def create_source(self, source: KnowledgeSource) -> KnowledgeSource:
        self.sources[source.id] = source
        return source

    async def create_item(self, item: KnowledgeItem) -> KnowledgeItem:
        self.items[item.id] = item
        return item

    async def create_chunk(self, chunk: KnowledgeChunk) -> KnowledgeChunk:
        self.chunks[chunk.id] = chunk
        return chunk

    async def search_records(
        self,
        *,
        tenant_id: UUID,
        query: str,
        agent_id: UUID | None = None,
        source_ids: set[UUID] | None = None,
        limit: int = 8,
    ) -> list[KnowledgeRecord]:
        records: list[KnowledgeRecord] = []
        for chunk in self.chunks.values():
            if chunk.tenant_id != tenant_id or chunk.status != "active":
                continue
            if source_ids and chunk.source_id not in source_ids:
                continue
            item = self.items.get(chunk.item_id)
            source = self.sources.get(chunk.source_id)
            if item is None or source is None:
                continue
            if (
                not item.active
                or item.status != "active"
                or source.status not in {"active", "partially_processed"}
            ):
                continue
            if not _agent_allowed(source, agent_id):
                continue
            score = score_text_match(
                query,
                chunk.chunk_text,
                content_type=source.content_type,
                title=item.title,
                source_name=source.name,
            )
            if score <= 0:
                continue
            records.append(KnowledgeRecord(source=source, item=item, chunk=chunk, score=score))
        records.sort(key=lambda r: (-r.score, -r.source.priority, r.item.title))
        return records[:limit]

    async def log_retrieval(
        self,
        *,
        tenant_id: UUID,
        agent_id: UUID | None,
        query: str,
        evidence: EvidencePack,
    ) -> UUID | None:
        self.logs.append(
            {
                "tenant_id": tenant_id,
                "agent_id": agent_id,
                "query": query,
                "answerable": evidence.answerable,
                "confidence": evidence.confidence,
                "citations": [c.model_dump(mode="json") for c in evidence.citations],
            }
        )
        return None


class SqlAlchemyKnowledgeRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_source(self, source: KnowledgeSource) -> KnowledgeSource:
        row = KnowledgeSourceRow(
            id=source.id,
            tenant_id=source.tenant_id,
            name=source.name,
            type=source.type,
            content_type=source.content_type,
            status=source.status,
            owner=source.owner,
            valid_from=source.valid_from,
            valid_until=source.valid_until,
            priority=source.priority,
            metadata_json=source.metadata,
        )
        self._session.add(row)
        await self._session.flush()
        return source

    async def create_item(self, item: KnowledgeItem) -> KnowledgeItem:
        row = KnowledgeItemRow(
            id=item.id,
            tenant_id=item.tenant_id,
            source_id=item.source_id,
            title=item.title,
            content=item.content,
            structured_data=item.structured_data,
            metadata_json=item.metadata,
            active=item.active,
            status=item.status,
        )
        self._session.add(row)
        await self._session.flush()
        return item

    async def create_chunk(self, chunk: KnowledgeChunk) -> KnowledgeChunk:
        row = KnowledgeChunkRow(
            id=chunk.id,
            tenant_id=chunk.tenant_id,
            source_id=chunk.source_id,
            item_id=chunk.item_id,
            chunk_text=chunk.chunk_text,
            chunk_index=chunk.chunk_index,
            embedding=chunk.embedding,
            metadata_json=chunk.metadata,
            status=chunk.status,
        )
        self._session.add(row)
        await self._session.flush()
        return chunk

    async def search_records(
        self,
        *,
        tenant_id: UUID,
        query: str,
        agent_id: UUID | None = None,
        source_ids: set[UUID] | None = None,
        limit: int = 8,
    ) -> list[KnowledgeRecord]:
        rows = (
            await self._session.execute(
                select(KnowledgeChunkRow, KnowledgeItemRow, KnowledgeSourceRow)
                .join(KnowledgeItemRow, KnowledgeChunkRow.item_id == KnowledgeItemRow.id)
                .join(KnowledgeSourceRow, KnowledgeChunkRow.source_id == KnowledgeSourceRow.id)
                .where(
                    KnowledgeChunkRow.tenant_id == tenant_id,
                    KnowledgeChunkRow.status == "active",
                    KnowledgeItemRow.active.is_(True),
                    KnowledgeItemRow.status == "active",
                    KnowledgeSourceRow.status.in_(("active", "partially_processed")),
                )
            )
        ).all()
        records: list[KnowledgeRecord] = []
        for chunk_row, item_row, source_row in rows:
            if source_ids and chunk_row.source_id not in source_ids:
                continue
            source = _source_from_row(source_row)
            if not _agent_allowed(source, agent_id):
                continue
            score = score_text_match(
                query,
                chunk_row.chunk_text,
                content_type=source_row.content_type,
                title=item_row.title,
                source_name=source_row.name,
            )
            if score <= 0:
                continue
            records.append(
                KnowledgeRecord(
                    source=source,
                    item=_item_from_row(item_row),
                    chunk=_chunk_from_row(chunk_row),
                    score=score,
                )
            )
        records.sort(key=lambda r: (-r.score, -r.source.priority, r.item.title))
        return records[:limit]

    async def log_retrieval(
        self,
        *,
        tenant_id: UUID,
        agent_id: UUID | None,
        query: str,
        evidence: EvidencePack,
    ) -> UUID | None:
        row = KnowledgeRetrievalLogRow(
            tenant_id=tenant_id,
            agent_id=agent_id,
            query=query,
            answerable=evidence.answerable,
            confidence=evidence.confidence,
            selected_chunk_ids=[str(c.chunk_id) for c in evidence.citations],
            citations_json=[c.model_dump(mode="json") for c in evidence.citations],
            metadata_json={"missing_info": evidence.missing_info},
        )
        self._session.add(row)
        await self._session.flush()
        return row.id


def score_text_match(
    query: str,
    text: str,
    *,
    content_type: str | None = None,
    title: str | None = None,
    source_name: str | None = None,
) -> float:
    query_terms = _terms(query)
    if not query_terms:
        return 0.0
    text_norm = normalize_match_text("\n".join(part for part in [title, source_name, text] if part))
    text_terms = set(text_norm.split())
    if content_type == "catalog" and not _catalog_query_matches_named_model(
        query_terms, text_terms
    ):
        return 0.0
    hits = sum(1 for term in query_terms if _term_matches_text(term, text_terms, text_norm))
    if hits == 0:
        return 0.0
    phrase_bonus = 0.25 if normalize_match_text(query) in text_norm else 0.0
    content_bonus = _content_type_boost(query, content_type)
    return min(1.0, hits / len(query_terms) + phrase_bonus + content_bonus)


def _terms(value: str) -> list[str]:
    normalized = normalize_match_text(value)
    if _short_reply_without_context(normalized):
        return []
    return [
        term
        for term in normalized.split()
        if term not in _MATCH_STOPWORDS
        and (len(term) >= 3 or any(char.isdigit() for char in term) or "%" in term)
    ]


def normalize_match_text(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    without_accents = "".join(
        char for char in decomposed if not unicodedata.combining(char)
    )
    cleaned = re.sub(r"[^a-z0-9%]+", " ", without_accents)
    return re.sub(r"\s+", " ", cleaned).strip()


def query_content_type_intents(query: str) -> set[str]:
    normalized = normalize_match_text(query)
    if not normalized:
        return set()
    intents: set[str] = set()
    credit_terms = {
        "credito",
        "creditos",
        "financiamiento",
        "financiar",
        "buro",
        "aprobar",
        "aprueban",
        "aprobacion",
    }
    pricing_terms = {
        "precio",
        "cuesta",
        "cuanto",
        "mensualidad",
        "mensualidades",
        "quincena",
        "enganche",
        "pago",
        "pagos",
    }
    document_terms = {
        "documento",
        "documentos",
        "requisito",
        "requisitos",
        "ine",
        "comprobante",
        "papeles",
    }
    location_terms = {
        "donde",
        "ubicacion",
        "ubicados",
        "sucursal",
        "direccion",
        "horario",
        "abren",
        "cierran",
    }
    appointment_terms = {
        "cita",
        "agenda",
        "agendar",
        "ir",
        "manana",
        "hoy",
        "visita",
        "pasar",
    }
    color_terms = {
        "color",
        "roja",
        "rojo",
        "azul",
        "negra",
        "negro",
        "blanca",
        "blanco",
        "disponible",
        "inventario",
        "stock",
    }
    if _has_any(normalized, credit_terms):
        intents.update({"credit_policy", "policy"})
    if _has_any(normalized, pricing_terms):
        intents.update({"pricing", "catalog"})
    if _has_any(normalized, {"adventure", "atom", "scooter"}):
        intents.add("catalog")
    if _has_any(normalized, document_terms):
        intents.add("document_rules")
    if _has_any(normalized, location_terms):
        intents.add("location_hours")
    if _has_any(normalized, appointment_terms):
        intents.add("appointment_rules")
    if _has_any(normalized, color_terms):
        intents.add("inventory_color_policy")
    return intents


def _content_type_boost(query: str, content_type: str | None) -> float:
    if not content_type:
        return 0.0
    normalized_type = content_type.strip().casefold()
    if normalized_type in query_content_type_intents(query):
        return 0.2
    return 0.0


def _short_reply_without_context(normalized: str) -> bool:
    short_replies = {
        "si",
        "ok",
        "va",
        "dale",
        "esa",
        "ese",
        "esa misma",
        "ese mismo",
        "manana",
    }
    return normalized in short_replies


def _has_any(value: str, terms: set[str]) -> bool:
    words = set(value.split())
    return bool(words.intersection(terms))


def _term_matches_text(term: str, text_terms: set[str], text_norm: str) -> bool:
    if term in text_terms:
        return True
    return any(char.isdigit() for char in term) and term in text_norm


def _catalog_query_matches_named_model(query_terms: list[str], text_terms: set[str]) -> bool:
    catalog_generic_terms = {
        "catalogo",
        "cotizar",
        "cotizacion",
        "precio",
        "cuesta",
        "cuanto",
        "credito",
        "creditos",
        "enganche",
        "pago",
        "pagos",
        "quincena",
        "quincenas",
    }
    named_terms = [
        term
        for term in query_terms
        if term not in catalog_generic_terms and not any(char.isdigit() for char in term)
    ]
    return not named_terms or any(term in text_terms for term in named_terms)


_MATCH_STOPWORDS = {
    "hola",
    "quiero",
    "quiere",
    "una",
    "uno",
    "unos",
    "unas",
    "moto",
    "motos",
    "para",
    "como",
    "con",
    "sin",
    "por",
    "que",
    "cual",
    "cuales",
    "puedo",
    "tengo",
    "dime",
    "me",
    "la",
    "el",
    "los",
    "las",
}


def _agent_allowed(source: KnowledgeSource, agent_id: UUID | None) -> bool:
    allowed = source.metadata.get("allowed_agent_ids")
    if not allowed or agent_id is None:
        return True
    return str(agent_id) in {str(value) for value in allowed}


def _source_from_row(row: KnowledgeSourceRow) -> KnowledgeSource:
    return KnowledgeSource(
        id=row.id,
        tenant_id=row.tenant_id,
        name=row.name,
        type=row.type,
        content_type=row.content_type,
        status=row.status,
        owner=row.owner,
        valid_from=row.valid_from,
        valid_until=row.valid_until,
        priority=row.priority,
        metadata=dict(row.metadata_json or {}),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _item_from_row(row: KnowledgeItemRow) -> KnowledgeItem:
    return KnowledgeItem(
        id=row.id,
        tenant_id=row.tenant_id,
        source_id=row.source_id,
        title=row.title,
        content=row.content,
        structured_data=dict(row.structured_data) if row.structured_data else None,
        metadata=dict(row.metadata_json or {}),
        active=row.active,
        status=row.status,
    )


def _chunk_from_row(row: KnowledgeChunkRow) -> KnowledgeChunk:
    return KnowledgeChunk(
        id=row.id,
        tenant_id=row.tenant_id,
        source_id=row.source_id,
        item_id=row.item_id,
        chunk_text=row.chunk_text,
        chunk_index=row.chunk_index,
        embedding=list(row.embedding) if row.embedding is not None else None,
        metadata=dict(row.metadata_json or {}),
        status=row.status,
    )
