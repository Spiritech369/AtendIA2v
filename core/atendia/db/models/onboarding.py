from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from atendia.db.base import Base


class OnboardingState(Base):
    __tablename__ = "onboarding_states"

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        primary_key=True,
    )
    selected_blueprint_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    channel_connected: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    knowledge_uploaded: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    agent_configured: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    contact_fields_ready: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="false",
    )
    lifecycle_ready: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    test_passed: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    published: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    current_step: Mapped[str] = mapped_column(
        String(80),
        default="select_blueprint",
        server_default="select_blueprint",
    )
    checklist: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
