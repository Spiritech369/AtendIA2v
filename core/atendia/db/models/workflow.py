from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from atendia.db.base import Base


class Workflow(Base):
    __tablename__ = "workflows"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    trigger_type: Mapped[str] = mapped_column(String(60), nullable=False)
    trigger_config: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    definition: Mapped[dict] = mapped_column(JSONB, default=dict, server_default='{"nodes":[],"edges":[]}')
    active: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # Optimistic-locking counter (migration 028). PATCH/toggle increments this
    # only when the client's expected version matches the row — two concurrent
    # admin edits result in 409 instead of last-write-wins.
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class WorkflowExecution(Base):
    __tablename__ = "workflow_executions"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workflow_id: Mapped[UUID] = mapped_column(ForeignKey("workflows.id", ondelete="CASCADE"), index=True)
    conversation_id: Mapped[UUID | None] = mapped_column(ForeignKey("conversations.id", ondelete="SET NULL"))
    customer_id: Mapped[UUID | None] = mapped_column(ForeignKey("customers.id", ondelete="SET NULL"))
    trigger_event_id: Mapped[UUID | None] = mapped_column()
    status: Mapped[str] = mapped_column(String(20), default="running", server_default="running")
    current_node_id: Mapped[str | None] = mapped_column(String(100))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(String(60))
    # Persisted across delay/resume so MAX_STEPS holds even if execution
    # pauses and re-enters via execute_workflow_step.
    steps_completed: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )


class WorkflowActionRun(Base):
    __tablename__ = "workflow_action_runs"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    execution_id: Mapped[UUID] = mapped_column(ForeignKey("workflow_executions.id", ondelete="CASCADE"))
    node_id: Mapped[str] = mapped_column(String(100), nullable=False)
    action_key: Mapped[str] = mapped_column(String(160), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WorkflowEventCursor(Base):
    __tablename__ = "workflow_event_cursors"

    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True)
    last_event_id: Mapped[UUID | None] = mapped_column(ForeignKey("events.id", ondelete="SET NULL"))
    last_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
