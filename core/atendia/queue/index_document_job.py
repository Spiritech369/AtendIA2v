from __future__ import annotations

import csv
from io import BytesIO, StringIO
from uuid import UUID

from openai import AsyncOpenAI
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from atendia.config import get_settings
from atendia.db.models.knowledge_document import KnowledgeChunk, KnowledgeDocument
from atendia.storage import get_storage_backend
from atendia.tools.embeddings import generate_embeddings_batch

MAX_PDF_PAGES = 100


async def index_document(ctx: dict, document_id: str) -> dict:
    settings = get_settings()
    engine = ctx.get("engine") or create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            doc = (
                await session.execute(
                    select(KnowledgeDocument).where(KnowledgeDocument.id == UUID(document_id))
                )
            ).scalar_one_or_none()
            if doc is None:
                return {"status": "missing"}
            try:
                data = await get_storage_backend().read(str(doc.tenant_id), doc.storage_path)
                text = _parse_document(doc.filename, data)
                chunks = _chunk_text(text)
                embeddings: list[list[float] | None] = [None] * len(chunks)
                if settings.openai_api_key and chunks:
                    client = AsyncOpenAI(api_key=settings.openai_api_key)
                    embedded, _tokens, _cost = await generate_embeddings_batch(client=client, texts=chunks)
                    embeddings = embedded
                await session.execute(delete(KnowledgeChunk).where(KnowledgeChunk.document_id == doc.id))
                for i, chunk in enumerate(chunks):
                    session.add(
                        KnowledgeChunk(
                            document_id=doc.id,
                            tenant_id=doc.tenant_id,
                            chunk_index=i,
                            text=chunk,
                            embedding=embeddings[i],
                        )
                    )
                doc.status = "indexed"
                doc.fragment_count = len(chunks)
                doc.error_message = None
            except Exception as exc:
                await session.execute(
                    update(KnowledgeDocument)
                    .where(KnowledgeDocument.id == doc.id)
                    .values(status="error", error_message=str(exc)[:1000])
                )
            await session.commit()
    finally:
        if "engine" not in ctx:
            await engine.dispose()
    return {"status": "ok", "document_id": document_id}


def _parse_document(filename: str, data: bytes) -> str:
    suffix = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    if suffix == "pdf":
        import fitz  # type: ignore[import-not-found]

        with fitz.open(stream=data, filetype="pdf") as pdf:
            if pdf.page_count > MAX_PDF_PAGES:
                raise ValueError(f"PDF has {pdf.page_count} pages; max supported is {MAX_PDF_PAGES}")
            texts = [page.get_text("text") for page in pdf]
        return "\n".join(texts)
    if suffix == "docx":
        from docx import Document  # type: ignore[import-not-found]

        doc = Document(BytesIO(data))
        return "\n".join(p.text for p in doc.paragraphs)
    if suffix == "xlsx":
        from openpyxl import load_workbook

        wb = load_workbook(BytesIO(data), read_only=True, data_only=True)
        lines: list[str] = []
        for ws in wb.worksheets[:10]:
            for row in ws.iter_rows(max_row=1000, values_only=True):
                values = [str(v) for v in row if v is not None]
                if values:
                    lines.append(", ".join(values))
        return "\n".join(lines)
    text = data.decode("utf-8", errors="ignore")
    if suffix == "csv":
        rows = csv.reader(StringIO(text))
        return "\n".join(", ".join(cell for cell in row) for _, row in zip(range(1000), rows, strict=False))
    return text


def _chunk_text(text: str, *, chunk_size: int = 2500, overlap: int = 250) -> list[str]:
    cleaned = "\n".join(line.strip() for line in text.splitlines() if line.strip())
    if not cleaned:
        return []
    chunks: list[str] = []
    start = 0
    while start < len(cleaned) and len(chunks) < 500:
        end = min(len(cleaned), start + chunk_size)
        chunks.append(cleaned[start:end])
        if end == len(cleaned):
            break
        start = max(0, end - overlap)
    return chunks
