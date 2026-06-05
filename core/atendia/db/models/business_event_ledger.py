from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from atendia.db.base import Base


class BusinessEventLedgerRow(Base):
    __tablename__ = "business_event_ledger"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "conversation_id",
            "event_type",
            "idempotency_key",
            name="uq_business_event_ledger_scope_idempotency_key",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    conversation_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    event_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="dry_run")
    reason: Mapped[str | None] = mapped_column(Text)
    event_payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    workflow_result: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    trace_id: Mapped[str | None] = mapped_column(String(120), index=True)
    side_effects_allowed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
