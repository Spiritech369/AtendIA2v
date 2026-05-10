from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Float, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from atendia.db.base import Base


class KbUnansweredQuestion(Base):
    __tablename__ = "kb_unanswered_questions"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    query_normalized: Mapped[str] = mapped_column(Text, nullable=False)
    agent: Mapped[str | None] = mapped_column(String(40))
    conversation_id: Mapped[UUID | None] = mapped_column()
    top_score: Mapped[float | None] = mapped_column(Float)
    llm_confidence: Mapped[str | None] = mapped_column(String(20))
    escalation_reason: Mapped[str | None] = mapped_column(Text)
    failed_chunks: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    suggested_answer: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="open", server_default="open")
    assigned_to: Mapped[UUID | None] = mapped_column()
    linked_faq_id: Mapped[UUID | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
