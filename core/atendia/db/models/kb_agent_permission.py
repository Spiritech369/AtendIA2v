from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from atendia.db.base import Base


class KbAgentPermission(Base):
    __tablename__ = "kb_agent_permissions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "agent", name="uq_kb_agent_perms"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    agent: Mapped[str] = mapped_column(String(40), nullable=False)
    allowed_source_types: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list, server_default="{}")
    allowed_collection_slugs: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list, server_default="{}")
    min_score: Mapped[float] = mapped_column(Float, default=0.7, server_default="0.7")
    can_quote_prices: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    can_quote_stock: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    required_customer_fields: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list, server_default="{}")
    escalate_on_conflict: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    fallback_message: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_by: Mapped[UUID | None] = mapped_column()
