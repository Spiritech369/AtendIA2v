from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from atendia.db.base import Base


class KbTestCase(Base):
    __tablename__ = "kb_test_cases"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    user_query: Mapped[str] = mapped_column(Text, nullable=False)
    expected_sources: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    expected_keywords: Mapped[list[str]] = mapped_column(
        ARRAY(Text), default=list, server_default="{}"
    )
    forbidden_phrases: Mapped[list[str]] = mapped_column(
        ARRAY(Text), default=list, server_default="{}"
    )
    agent: Mapped[str] = mapped_column(String(40), nullable=False)
    required_customer_fields: Mapped[list[str]] = mapped_column(
        ARRAY(Text), default=list, server_default="{}"
    )
    expected_action: Mapped[str] = mapped_column(
        String(20), default="answer", server_default="answer"
    )
    minimum_score: Mapped[float] = mapped_column(Float, default=0.7, server_default="0.7")
    is_critical: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    created_by: Mapped[UUID | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
