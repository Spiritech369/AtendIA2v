from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from atendia.db.base import Base


class AgentReadinessEvalResult(Base):
    __tablename__ = "agent_readiness_eval_results"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    agent_id: Mapped[UUID] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    suite_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    blueprint_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    score: Mapped[float] = mapped_column(Numeric(5, 4), nullable=False)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    scenario_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    failed_scenarios: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    policy_failures: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by: Mapped[UUID | None] = mapped_column(
        ForeignKey("tenant_users.id", ondelete="SET NULL"),
        nullable=True,
    )
    metadata_json: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, server_default="{}")
