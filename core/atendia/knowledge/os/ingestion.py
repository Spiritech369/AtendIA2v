from __future__ import annotations

import csv
from io import StringIO
from pathlib import Path
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from atendia.knowledge.os.chunking import chunk_text
from atendia.knowledge.os.parsers import ParsedDocument, ParsedTable, parse_file
from atendia.knowledge.os.schemas import (
    KnowledgeChunk,
    KnowledgeContentType,
    KnowledgeItem,
    KnowledgeSource,
    KnowledgeSourceStatus,
    KnowledgeSourceType,
)
from atendia.knowledge.os.service import KnowledgeRepository


class FAQSeed(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str
    answer: str
    metadata: dict = Field(default_factory=dict)


class KnowledgeIngestionService:
    def __init__(self, repository: KnowledgeRepository) -> None:
        self._repository = repository

    async def ingest_manual_text(
        self,
        *,
        tenant_id: UUID,
        name: str,
        content: str,
        title: str | None = None,
        content_type: KnowledgeContentType = "general",
        metadata: dict | None = None,
    ) -> tuple[KnowledgeSource, list[KnowledgeItem], list[KnowledgeChunk]]:
        source = await self._create_source(
            tenant_id=tenant_id,
            name=name,
            source_type="manual",
            content_type=content_type,
            metadata=metadata or {},
        )
        item = await self._create_item(
            tenant_id=tenant_id,
            source_id=source.id,
            title=title or name,
            content=content,
            metadata={"ingestion": "manual_text"},
        )
        chunks = await self._create_chunks(item=item, source=source)
        return source, [item], chunks

    async def ingest_faqs(
        self,
        *,
        tenant_id: UUID,
        name: str,
        faqs: list[FAQSeed],
        metadata: dict | None = None,
    ) -> tuple[KnowledgeSource, list[KnowledgeItem], list[KnowledgeChunk]]:
        source = await self._create_source(
            tenant_id=tenant_id,
            name=name,
            source_type="faq",
            content_type="faq",
            metadata=metadata or {},
        )
        items: list[KnowledgeItem] = []
        chunks: list[KnowledgeChunk] = []
        for faq in faqs:
            content = f"{faq.question}\n{faq.answer}"
            item = await self._create_item(
                tenant_id=tenant_id,
                source_id=source.id,
                title=faq.question,
                content=content,
                structured_data={"question": faq.question, "answer": faq.answer},
                metadata={"ingestion": "faq", **faq.metadata},
            )
            items.append(item)
            chunks.extend(await self._create_chunks(item=item, source=source))
        return source, items, chunks

    async def ingest_csv_text(
        self,
        *,
        tenant_id: UUID,
        name: str,
        csv_text: str,
        content_type: KnowledgeContentType = "general",
        metadata: dict | None = None,
    ) -> tuple[KnowledgeSource, list[KnowledgeItem], list[KnowledgeChunk]]:
        source = await self._create_source(
            tenant_id=tenant_id,
            name=name,
            source_type="table",
            content_type=content_type,
            metadata=metadata or {},
        )
        reader = csv.DictReader(StringIO(csv_text))
        items: list[KnowledgeItem] = []
        chunks: list[KnowledgeChunk] = []
        for index, row in enumerate(reader):
            normalized = {str(k): str(v or "") for k, v in row.items() if k is not None}
            title = normalized.get("title") or normalized.get("name") or f"{name} row {index + 1}"
            content = "\n".join(f"{key}: {value}" for key, value in normalized.items() if value)
            if not content:
                continue
            item = await self._create_item(
                tenant_id=tenant_id,
                source_id=source.id,
                title=title,
                content=content,
                structured_data=normalized,
                metadata={"ingestion": "csv", "row_index": index},
            )
            items.append(item)
            chunks.extend(await self._create_chunks(item=item, source=source))
        return source, items, chunks

    async def ingest_file(
        self,
        *,
        tenant_id: UUID,
        name: str,
        filename: str,
        data: bytes,
        content_type: KnowledgeContentType = "general",
        metadata: dict | None = None,
    ) -> tuple[KnowledgeSource, list[KnowledgeItem], list[KnowledgeChunk]]:
        source_type: KnowledgeSourceType = (
            "table" if _suffix(filename) in {"csv", "tsv", "xlsx"} else "file"
        )
        try:
            parsed = parse_file(data, filename=filename)
        except Exception as exc:
            source = await self._create_source(
                tenant_id=tenant_id,
                name=name,
                source_type=source_type,
                content_type=content_type,
                metadata={
                    **(metadata or {}),
                    "filename": filename,
                    "file_type": _suffix(filename),
                    "ingestion_status": "error",
                    "error": str(exc),
                },
                status="error",
            )
            return source, [], []

        status = _status_from_parsed(parsed)
        source = await self._create_source(
            tenant_id=tenant_id,
            name=name,
            source_type=source_type,
            content_type=content_type,
            metadata={
                **(metadata or {}),
                **parsed.metadata,
                "filename": filename,
                "file_type": _suffix(filename),
                "ingestion_status": status,
                "warnings": list(parsed.warnings),
            },
            status=status,
        )
        items: list[KnowledgeItem] = []
        chunks: list[KnowledgeChunk] = []
        items.extend(
            await self._items_from_sections(
                tenant_id=tenant_id,
                source=source,
                parsed=parsed,
                fallback_title=name,
            )
        )
        items.extend(
            await self._items_from_tables(
                tenant_id=tenant_id,
                source=source,
                tables=parsed.tables,
                fallback_title=name,
            )
        )
        for item in items:
            chunks.extend(await self._create_chunks(item=item, source=source))
        return source, items, chunks

    async def ingest_text_file(
        self,
        *,
        tenant_id: UUID,
        name: str,
        filename: str,
        data: bytes,
        content_type: KnowledgeContentType = "general",
    ) -> tuple[KnowledgeSource, list[KnowledgeItem], list[KnowledgeChunk]]:
        return await self.ingest_file(
            tenant_id=tenant_id,
            name=name,
            filename=filename,
            data=data,
            content_type=content_type,
        )

    async def _create_source(
        self,
        *,
        tenant_id: UUID,
        name: str,
        source_type: KnowledgeSourceType,
        content_type: KnowledgeContentType,
        metadata: dict,
        status: KnowledgeSourceStatus = "active",
    ) -> KnowledgeSource:
        return await self._repository.create_source(
            KnowledgeSource(
                tenant_id=tenant_id,
                name=name,
                type=source_type,
                content_type=content_type,
                status=status,
                metadata=metadata,
            )
        )

    async def _create_item(
        self,
        *,
        tenant_id: UUID,
        source_id: UUID,
        title: str,
        content: str,
        structured_data: dict | None = None,
        metadata: dict | None = None,
    ) -> KnowledgeItem:
        return await self._repository.create_item(
            KnowledgeItem(
                tenant_id=tenant_id,
                source_id=source_id,
                title=title,
                content=content,
                structured_data=structured_data,
                metadata=metadata or {},
            )
        )

    async def _create_chunks(
        self,
        *,
        item: KnowledgeItem,
        source: KnowledgeSource,
    ) -> list[KnowledgeChunk]:
        chunks: list[KnowledgeChunk] = []
        for index, text in enumerate(chunk_text(item.content)):
            chunk = await self._repository.create_chunk(
                KnowledgeChunk(
                    tenant_id=item.tenant_id,
                    source_id=source.id,
                    item_id=item.id,
                    chunk_text=text,
                    chunk_index=index,
                    metadata={
                        "source_name": source.name,
                        "item_title": item.title,
                        **item.metadata,
                    },
                )
            )
            chunks.append(chunk)
        return chunks

    async def _items_from_sections(
        self,
        *,
        tenant_id: UUID,
        source: KnowledgeSource,
        parsed: ParsedDocument,
        fallback_title: str,
    ) -> list[KnowledgeItem]:
        items: list[KnowledgeItem] = []
        sections = parsed.sections
        if not sections and parsed.extracted_text:
            item = await self._create_item(
                tenant_id=tenant_id,
                source_id=source.id,
                title=fallback_title,
                content=parsed.extracted_text,
                metadata={"ingestion": "file", **parsed.metadata},
            )
            return [item]
        for index, section in enumerate(sections, start=1):
            if not section.text.strip():
                continue
            item = await self._create_item(
                tenant_id=tenant_id,
                source_id=source.id,
                title=section.title or f"{fallback_title} section {index}",
                content=section.text,
                metadata={
                    "ingestion": "file",
                    "section_index": index,
                    **parsed.metadata,
                    **section.metadata,
                },
            )
            items.append(item)
        return items

    async def _items_from_tables(
        self,
        *,
        tenant_id: UUID,
        source: KnowledgeSource,
        tables: list[ParsedTable],
        fallback_title: str,
    ) -> list[KnowledgeItem]:
        items: list[KnowledgeItem] = []
        for table_index, table in enumerate(tables, start=1):
            for row_index, row in enumerate(table.rows, start=1):
                content = _table_row_content(row, headers=table.headers)
                if not content:
                    continue
                reference = {
                    "table_index": table_index,
                    "row_index": row_index,
                    **table.reference,
                }
                title = _table_row_title(row, fallback=f"{fallback_title} row {row_index}")
                item = await self._create_item(
                    tenant_id=tenant_id,
                    source_id=source.id,
                    title=title,
                    content=content,
                    structured_data=row,
                    metadata={
                        "ingestion": "table",
                        "headers": table.headers,
                        **table.metadata,
                        **reference,
                    },
                )
                items.append(item)
        return items


def _suffix(filename: str) -> str:
    return Path(filename or "").suffix.lower().lstrip(".")


def _status_from_parsed(parsed: ParsedDocument) -> KnowledgeSourceStatus:
    if not parsed.extracted_text and not any(table.rows for table in parsed.tables):
        return "partially_processed" if parsed.warnings else "error"
    return "partially_processed" if parsed.warnings else "active"


def _table_row_content(row: dict[str, Any], *, headers: list[str]) -> str:
    ordered_keys = headers or list(row)
    parts = [f"{key}: {row.get(key)}" for key in ordered_keys if str(row.get(key) or "").strip()]
    return "\n".join(parts)


def _table_row_title(row: dict[str, Any], *, fallback: str) -> str:
    for key, value in row.items():
        key_norm = str(key).casefold()
        if key_norm in {"title", "name", "nombre", "product", "producto", "service", "servicio"}:
            text = str(value or "").strip()
            if text:
                return text
    for value in row.values():
        text = str(value or "").strip()
        if text:
            return text[:120]
    return fallback
