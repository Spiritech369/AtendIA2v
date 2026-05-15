from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from atendia.db.base import Base


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    role: Mapped[str] = mapped_column(String(40), default="custom", server_default="custom")
    status: Mapped[str] = mapped_column(
        String(20), default="production", server_default="production"
    )
    behavior_mode: Mapped[str] = mapped_column(
        String(20), default="normal", server_default="normal"
    )
    version: Mapped[str] = mapped_column(String(20), default="v2.4", server_default="v2.4")
    dealership_id: Mapped[str | None] = mapped_column(String(80))
    branch_id: Mapped[str | None] = mapped_column(String(80))
    goal: Mapped[str | None] = mapped_column(Text)
    style: Mapped[str | None] = mapped_column(String(200))
    tone: Mapped[str | None] = mapped_column(
        String(40), default="amigable", server_default="amigable"
    )
    language: Mapped[str | None] = mapped_column(String(20), default="es", server_default="es")
    max_sentences: Mapped[int | None] = mapped_column(Integer, default=5, server_default="5")
    no_emoji: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    return_to_flow: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    system_prompt: Mapped[str | None] = mapped_column(Text)
    active_intents: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    extraction_config: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    auto_actions: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    knowledge_config: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    flow_mode_rules: Mapped[dict | None] = mapped_column(JSONB)
    ops_config: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
