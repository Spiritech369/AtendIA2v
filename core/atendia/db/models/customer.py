from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from atendia.db.base import Base


class Customer(Base):
    __tablename__ = "customers"
    __table_args__ = (
        UniqueConstraint("tenant_id", "phone_e164", name="uq_customers_tenant_phone"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    phone_e164: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    name: Mapped[str | None] = mapped_column(String(160))
    # Re-added in migration 029 (was in v1, dropped in initial v2 schema).
    email: Mapped[str | None] = mapped_column(String(160))
    score: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    attrs: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
