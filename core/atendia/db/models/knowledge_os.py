from datetime import datetime
from uuid import UUID, uuid4

from pgvector.sqlalchemy import HALFVEC  # type: ignore[import-untyped]
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from atendia.db.base import Base
from atendia.db.models.tenant_config import EMBEDDING_DIM


class KnowledgeSource(Base):
    __tablename__ = "knowledge_sources"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    type: Mapped[str] = mapped_column(String(40), nullable=False)
    content_type: Mapped[str] = mapped_column(String(60), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="draft", server_default="draft")
    owner: Mapped[str | None] = mapped_column(String(160))
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    priority: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    metadata_json: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class KnowledgeItem(Base):
    __tablename__ = "knowledge_items"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    source_id: Mapped[UUID] = mapped_column(
        ForeignKey("knowledge_sources.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    structured_data: Mapped[dict | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(30), default="active", server_default="active")
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    metadata_json: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class KnowledgeOSChunk(Base):
    __tablename__ = "knowledge_os_chunks"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    source_id: Mapped[UUID] = mapped_column(
        ForeignKey("knowledge_sources.id", ondelete="CASCADE"), index=True
    )
    item_id: Mapped[UUID] = mapped_column(
        ForeignKey("knowledge_items.id", ondelete="CASCADE"), index=True
    )
    chunk_text: Mapped[str] = mapped_column(Text, nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(HALFVEC(EMBEDDING_DIM), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="active", server_default="active")
    metadata_json: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class KnowledgeRetrievalLog(Base):
    __tablename__ = "knowledge_retrieval_logs"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    agent_id: Mapped[UUID | None] = mapped_column(ForeignKey("agents.id", ondelete="SET NULL"))
    query: Mapped[str] = mapped_column(Text, nullable=False)
    answerable: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    confidence: Mapped[float] = mapped_column(Float, default=0.0, server_default="0")
    selected_chunk_ids: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    citations_json: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    metadata_json: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
