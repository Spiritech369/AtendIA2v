from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from atendia.db.base import Base


class Appointment(Base):
    __tablename__ = "appointments"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    customer_id: Mapped[UUID] = mapped_column(ForeignKey("customers.id", ondelete="CASCADE"), index=True)
    conversation_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True
    )
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    appointment_type: Mapped[str] = mapped_column(String(30), default="follow_up", server_default="follow_up")
    service: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="scheduled", server_default="scheduled")
    timezone: Mapped[str] = mapped_column(String(80), default="America/Mexico_City", server_default="America/Mexico_City")
    source: Mapped[str] = mapped_column(String(40), default="manual", server_default="manual")
    advisor_id: Mapped[str | None] = mapped_column(String(80))
    advisor_name: Mapped[str | None] = mapped_column(String(160))
    vehicle_id: Mapped[str | None] = mapped_column(String(80))
    vehicle_label: Mapped[str | None] = mapped_column(String(160))
    ai_confidence: Mapped[float | None] = mapped_column(Float)
    risk_score: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    risk_level: Mapped[str] = mapped_column(String(20), default="low", server_default="low")
    risk_reasons: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    recommended_actions: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    credit_plan: Mapped[str | None] = mapped_column(String(120))
    down_payment_amount: Mapped[int | None] = mapped_column(Integer)
    down_payment_confirmed: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    documents_complete: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    last_customer_reply_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    arrived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    no_show_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reminder_status: Mapped[str] = mapped_column(String(30), default="pending", server_default="pending")
    reminder_last_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    action_log: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    ops_config: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    notes: Mapped[str | None] = mapped_column(Text)
    created_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("tenant_users.id", ondelete="SET NULL"), nullable=True
    )
    created_by_type: Mapped[str] = mapped_column(String(10), default="user", server_default="user")
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
