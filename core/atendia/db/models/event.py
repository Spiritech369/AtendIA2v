from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from atendia.db.base import Base


class EventRow(Base):
    __tablename__ = "events"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    # Nullable after migration 028: admin audit events (workflow created,
    # KB document uploaded, etc.) don't have a conversation context. The
    # state-machine emitter still always sets it for runtime events.
    conversation_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    type: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    trace_id: Mapped[str | None] = mapped_column(String(60), index=True)
    # Migration 028: who took this action. NULL when the writer is the system
    # (workflow engine, NLU, runner). Set for operator-initiated audit events.
    actor_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("tenant_users.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Set by the workflow engine when an event is the side-effect of a workflow
    # execution. ``evaluate_event`` skips events whose source matches the
    # candidate workflow so a workflow can't trigger itself.
    source_workflow_execution_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("workflow_executions.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
