from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from atendia.db.base import Base


_DEFAULT_FALLBACK_ES_MX = (
    "Déjame validarlo con un asesor para darte la información correcta."
)


class KbSafeAnswerSetting(Base):
    __tablename__ = "kb_safe_answer_settings"

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True
    )
    min_score_to_answer: Mapped[float] = mapped_column(Float, default=0.7, server_default="0.7")
    escalate_on_conflict: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    block_invented_prices: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    block_invented_stock: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    risky_phrases: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    default_fallback_message: Mapped[str] = mapped_column(
        Text, nullable=False, default=_DEFAULT_FALLBACK_ES_MX, server_default=_DEFAULT_FALLBACK_ES_MX,
    )
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_by: Mapped[UUID | None] = mapped_column()
