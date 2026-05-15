from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from atendia.db.base import Base


class KbConflict(Base):
    __tablename__ = "kb_conflicts"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    detection_type: Mapped[str] = mapped_column(String(30), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), default="medium", server_default="medium")
    status: Mapped[str] = mapped_column(String(20), default="open", server_default="open")
    entity_a_type: Mapped[str] = mapped_column(String(20), nullable=False)
    entity_a_id: Mapped[UUID] = mapped_column(nullable=False)
    entity_a_excerpt: Mapped[str | None] = mapped_column(Text)
    entity_b_type: Mapped[str] = mapped_column(String(20), nullable=False)
    entity_b_id: Mapped[UUID] = mapped_column(nullable=False)
    entity_b_excerpt: Mapped[str | None] = mapped_column(Text)
    suggested_priority: Mapped[str | None] = mapped_column(Text)
    assigned_to: Mapped[UUID | None] = mapped_column()
    resolved_by: Mapped[UUID | None] = mapped_column()
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolution_action: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
