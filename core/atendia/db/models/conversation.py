from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from atendia.db.base import Base


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    customer_id: Mapped[UUID] = mapped_column(ForeignKey("customers.id", ondelete="CASCADE"), index=True)
    channel: Mapped[str] = mapped_column(String(40), default="whatsapp_meta")
    status: Mapped[str] = mapped_column(String(20), default="active")
    current_stage: Mapped[str] = mapped_column(String(60), default="greeting")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_activity_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    state: Mapped["ConversationStateRow"] = relationship(back_populates="conversation", uselist=False)


class ConversationStateRow(Base):
    __tablename__ = "conversation_state"

    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), primary_key=True
    )
    extracted_data: Mapped[dict] = mapped_column(JSONB, default=dict)
    pending_confirmation: Mapped[str | None] = mapped_column(String(160))
    last_intent: Mapped[str | None] = mapped_column(String(40))
    stage_entered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    followups_sent_count: Mapped[int] = mapped_column(Integer, default=0)
    total_cost_usd: Mapped[Decimal] = mapped_column(Numeric(10, 6), default=Decimal("0"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    conversation: Mapped[Conversation] = relationship(back_populates="state")
