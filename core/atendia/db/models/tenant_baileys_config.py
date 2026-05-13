from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from atendia.db.base import Base


class TenantBaileysConfig(Base):
    """Per-tenant configuration for the Baileys WhatsApp channel.

    Mirrors what the sidecar reports plus a `prefer_over_meta` toggle the
    tenant flips when they want outbound messages to go through Baileys
    instead of Meta Cloud API.
    """

    __tablename__ = "tenant_baileys_config"

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    connected_phone: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_status: Mapped[str] = mapped_column(
        String(20), default="disconnected", server_default="disconnected"
    )
    last_status_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    prefer_over_meta: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "last_status IN ('disconnected','connecting','qr_pending','connected','error')",
            name="ck_baileys_status",
        ),
    )
