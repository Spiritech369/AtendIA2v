from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from atendia.db.base import Base


class KbTestRun(Base):
    __tablename__ = "kb_test_runs"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    test_case_id: Mapped[UUID] = mapped_column(
        ForeignKey("kb_test_cases.id", ondelete="CASCADE"), index=True
    )
    run_id: Mapped[UUID] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    retrieved_sources: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    generated_answer: Mapped[str | None] = mapped_column(Text)
    diff_vs_expected: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    failure_reasons: Mapped[list[str]] = mapped_column(
        ARRAY(Text), default=list, server_default="{}"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
