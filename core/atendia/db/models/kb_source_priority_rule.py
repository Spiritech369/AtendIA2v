from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from atendia.db.base import Base


class KbSourcePriorityRule(Base):
    __tablename__ = "kb_source_priority_rules"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    agent: Mapped[str | None] = mapped_column(String(40))
    source_type: Mapped[str] = mapped_column(String(20), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    minimum_score: Mapped[float] = mapped_column(Float, default=0.7, server_default="0.7")
    allow_synthesis: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    allow_direct_answer: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    escalation_required_when_conflict: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true"
    )
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
