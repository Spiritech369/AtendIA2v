from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from atendia.db.base import Base


class Customer(Base):
    __tablename__ = "customers"
    __table_args__ = (
        UniqueConstraint("tenant_id", "phone_e164", name="uq_customers_tenant_phone"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    phone_e164: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    name: Mapped[str | None] = mapped_column(String(160))
    # Re-added in migration 029 (was in v1, dropped in initial v2 schema).
    email: Mapped[str | None] = mapped_column(String(160))
    score: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    attrs: Mapped[dict] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(40), default="active", server_default="active")
    stage: Mapped[str] = mapped_column(String(60), default="new", server_default="new", index=True)
    source: Mapped[str | None] = mapped_column(String(80))
    tags: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    assigned_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("tenant_users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    last_activity_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    health_score: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    risk_level: Mapped[str] = mapped_column(String(20), default="low", server_default="low")
    sla_status: Mapped[str] = mapped_column(
        String(20), default="on_track", server_default="on_track"
    )
    next_best_action: Mapped[str | None] = mapped_column(String(60))
    ai_summary: Mapped[str | None] = mapped_column(Text)
    ai_insight_reason: Mapped[str | None] = mapped_column(Text)
    ai_confidence: Mapped[float | None] = mapped_column(Float)
    documents_status: Mapped[str] = mapped_column(
        String(30), default="missing", server_default="missing"
    )
    last_ai_action_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_human_action_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class CustomerScore(Base):
    __tablename__ = "customer_scores"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    customer_id: Mapped[UUID] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), index=True
    )
    total_score: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    intent_score: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    activity_score: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    documentation_score: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    data_quality_score: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    conversation_engagement_score: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0"
    )
    stage_progress_score: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    abandonment_risk_score: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    explanation: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    calculated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class CustomerRisk(Base):
    __tablename__ = "customer_risks"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    customer_id: Mapped[UUID] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), index=True
    )
    risk_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(20), default="medium", server_default="medium")
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    recommended_action: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default="open", server_default="open", index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CustomerNextBestAction(Base):
    __tablename__ = "customer_next_best_actions"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    customer_id: Mapped[UUID] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), index=True
    )
    action_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    priority: Mapped[int] = mapped_column(Integer, default=50, server_default="50")
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.7, server_default="0.7")
    suggested_message: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        String(20), default="active", server_default="active", index=True
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CustomerTimelineEvent(Base):
    __tablename__ = "customer_timeline_events"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    customer_id: Mapped[UUID] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), index=True
    )
    event_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    actor_type: Mapped[str] = mapped_column(String(30), default="system", server_default="system")
    actor_id: Mapped[UUID | None] = mapped_column(nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class CustomerDocument(Base):
    __tablename__ = "customer_documents"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    customer_id: Mapped[UUID] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), index=True
    )
    document_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    label: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="missing", server_default="missing")
    file_url: Mapped[str | None] = mapped_column(Text)
    uploaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class CustomerAIReviewItem(Base):
    __tablename__ = "customer_ai_review_items"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    customer_id: Mapped[UUID] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), index=True
    )
    conversation_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    issue_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(20), default="medium", server_default="medium")
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    ai_summary: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float | None] = mapped_column(Float)
    risky_output_flag: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    human_review_required: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true"
    )
    status: Mapped[str] = mapped_column(
        String(20), default="open", server_default="open", index=True
    )
    feedback_status: Mapped[str | None] = mapped_column(String(30))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
