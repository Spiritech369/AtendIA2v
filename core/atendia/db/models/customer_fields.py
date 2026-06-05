from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from atendia.db.base import Base


class CustomerFieldDefinition(Base):
    __tablename__ = "customer_field_definitions"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        index=True,
    )
    key: Mapped[str] = mapped_column(String(120), nullable=False)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    field_type: Mapped[str] = mapped_column(String(40), nullable=False)
    field_options: Mapped[dict | None] = mapped_column(JSONB, default=None)
    ordering: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )


class CustomerFieldValue(Base):
    __tablename__ = "customer_field_values"

    customer_id: Mapped[UUID] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"),
        primary_key=True,
    )
    field_definition_id: Mapped[UUID] = mapped_column(
        ForeignKey("customer_field_definitions.id", ondelete="CASCADE"),
        primary_key=True,
    )
    value: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class CustomerFieldUpdateEvidence(Base):
    __tablename__ = "customer_field_update_evidence"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        index=True,
    )
    customer_id: Mapped[UUID] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"),
        index=True,
    )
    field_definition_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("customer_field_definitions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    field_key: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    old_value: Mapped[str | None] = mapped_column(Text)
    new_value: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(40), nullable=False)
    evidence_message_id: Mapped[UUID | None] = mapped_column(nullable=True)
    evidence_attachment_id: Mapped[UUID | None] = mapped_column(nullable=True)
    reason: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float, default=0.0, server_default="0")
    status: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    trace_id: Mapped[str | None] = mapped_column(String(120))
    created_by: Mapped[str | None] = mapped_column(String(120))
    metadata_json: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
