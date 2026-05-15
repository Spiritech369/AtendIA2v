from datetime import datetime
from uuid import UUID, uuid4

from pgvector.sqlalchemy import HALFVEC  # type: ignore[import-untyped]
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from atendia.db.base import Base
from atendia.db.models.tenant_config import EMBEDDING_DIM


class KnowledgeDocument(Base):
    __tablename__ = "knowledge_documents"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_path: Mapped[str] = mapped_column(String(500), nullable=False)
    category: Mapped[str | None] = mapped_column(String(60))
    status: Mapped[str] = mapped_column(
        String(20), default="processing", server_default="processing"
    )
    fragment_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Phase B2 KB module — added in migration 032 (shared metadata + doc-specific).
    visibility: Mapped[str] = mapped_column(String(20), default="agents", server_default="agents")
    priority: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[UUID | None] = mapped_column()
    updated_by: Mapped[UUID | None] = mapped_column()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    agent_permissions: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    collection_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("kb_collections.id", ondelete="SET NULL")
    )
    language: Mapped[str] = mapped_column(String(8), default="es-MX", server_default="es-MX")
    progress_percentage: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    embedded_chunk_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    error_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("knowledge_documents.id", ondelete="CASCADE"), index=True
    )
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(HALFVEC(EMBEDDING_DIM), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Phase B2 KB module — added in migration 032.
    chunk_status: Mapped[str] = mapped_column(
        String(20), default="embedded", server_default="embedded"
    )
    marked_critical: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    error_message: Mapped[str | None] = mapped_column(Text)
    token_count: Mapped[int | None] = mapped_column(Integer)
    page: Mapped[int | None] = mapped_column(Integer)
    heading: Mapped[str | None] = mapped_column(Text)
    section: Mapped[str | None] = mapped_column(Text)
    last_retrieved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retrieval_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    average_score: Mapped[float | None] = mapped_column(Float)
