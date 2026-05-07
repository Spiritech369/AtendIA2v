from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from pgvector.sqlalchemy import HALFVEC  # type: ignore[import-untyped]
from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from atendia.db.base import Base

# text-embedding-3-large produces 3072-dim vectors. Stored as halfvec
# (16-bit floats) so we stay under pgvector's 2000-dim HNSW cap for
# the standard `vector` type. See migration 013 for the rationale.
EMBEDDING_DIM: int = 3072


class TenantPipeline(Base):
    __tablename__ = "tenant_pipelines"
    __table_args__ = (
        UniqueConstraint("tenant_id", "version", name="uq_tenant_pipelines_tenant_version"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    definition: Mapped[dict] = mapped_column(JSONB, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TenantCatalogItem(Base):
    __tablename__ = "tenant_catalogs"
    __table_args__ = (
        UniqueConstraint("tenant_id", "sku", name="uq_tenant_catalogs_tenant_sku"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    sku: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    attrs: Mapped[dict] = mapped_column(JSONB, default=dict)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Phase 3c.1
    category: Mapped[str | None] = mapped_column(String(60), nullable=True)
    embedding: Mapped[list[float] | None] = mapped_column(HALFVEC(EMBEDDING_DIM), nullable=True)


class TenantFAQ(Base):
    __tablename__ = "tenant_faqs"
    __table_args__ = (
        UniqueConstraint("tenant_id", "question", name="uq_tenant_faqs_tenant_question"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    question: Mapped[str] = mapped_column(String(500), nullable=False)
    answer: Mapped[str] = mapped_column(String(2000), nullable=False)
    tags: Mapped[list] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Phase 3c.1
    embedding: Mapped[list[float] | None] = mapped_column(HALFVEC(EMBEDDING_DIM), nullable=True)


class TenantTemplateMeta(Base):
    __tablename__ = "tenant_templates_meta"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "template_name", "language",
            name="uq_tenant_templates_meta",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    template_name: Mapped[str] = mapped_column(String(120), nullable=False)
    category: Mapped[str] = mapped_column(String(20), nullable=False)
    language: Mapped[str] = mapped_column(String(10), default="es_MX")
    body_template: Mapped[str] = mapped_column(Text, nullable=False)
    cost_estimate_usd: Mapped[Decimal] = mapped_column(Numeric(10, 6), default=Decimal("0"))
    last_approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TenantToolConfig(Base):
    __tablename__ = "tenant_tools_config"
    __table_args__ = (
        UniqueConstraint("tenant_id", "tool_name", name="uq_tenant_tools_config"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    tool_name: Mapped[str] = mapped_column(String(60), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    config: Mapped[dict] = mapped_column(JSONB, default=dict)


class TenantBranding(Base):
    __tablename__ = "tenant_branding"

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True
    )
    bot_name: Mapped[str] = mapped_column(String(80), default="Asistente")
    voice: Mapped[dict] = mapped_column(JSONB, default=dict)
    default_messages: Mapped[dict] = mapped_column(JSONB, default=dict)
