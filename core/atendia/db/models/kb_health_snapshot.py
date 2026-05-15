from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from atendia.db.base import Base


class KbHealthSnapshot(Base):
    __tablename__ = "kb_health_snapshots"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    snapshot_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    score_components: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    main_risks: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    suggested_actions: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    per_collection_scores: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
