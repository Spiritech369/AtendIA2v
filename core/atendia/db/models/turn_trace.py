from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from atendia.db.base import Base


class TurnTrace(Base):
    __tablename__ = "turn_traces"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    turn_number: Mapped[int] = mapped_column(Integer, nullable=False)

    inbound_message_id: Mapped[UUID | None] = mapped_column(ForeignKey("messages.id"))
    inbound_text: Mapped[str | None] = mapped_column(Text)

    nlu_input: Mapped[dict | None] = mapped_column(JSONB)
    nlu_output: Mapped[dict | None] = mapped_column(JSONB)
    nlu_model: Mapped[str | None] = mapped_column(String(60))
    nlu_tokens_in: Mapped[int | None] = mapped_column(Integer)
    nlu_tokens_out: Mapped[int | None] = mapped_column(Integer)
    nlu_cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    nlu_latency_ms: Mapped[int | None] = mapped_column(Integer)

    state_before: Mapped[dict | None] = mapped_column(JSONB)
    state_after: Mapped[dict | None] = mapped_column(JSONB)
    stage_transition: Mapped[str | None] = mapped_column(String(120))

    composer_input: Mapped[dict | None] = mapped_column(JSONB)
    composer_output: Mapped[dict | None] = mapped_column(JSONB)
    composer_model: Mapped[str | None] = mapped_column(String(60))
    composer_tokens_in: Mapped[int | None] = mapped_column(Integer)
    composer_tokens_out: Mapped[int | None] = mapped_column(Integer)
    composer_cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    composer_latency_ms: Mapped[int | None] = mapped_column(Integer)

    # Phase 3c.1: per-turn tool cost (initially OpenAI Embeddings spent
    # inside lookup_faq / search_catalog). Migration 014.
    tool_cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))

    # Phase 3c.2: routing + vision
    flow_mode: Mapped[str | None] = mapped_column(String(20))
    vision_cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    vision_latency_ms: Mapped[int | None] = mapped_column(Integer)

    outbound_messages: Mapped[list | None] = mapped_column(JSONB)

    total_cost_usd: Mapped[Decimal] = mapped_column(Numeric(10, 6), default=Decimal("0"))
    total_latency_ms: Mapped[int | None] = mapped_column(Integer)

    errors: Mapped[list | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    tool_calls: Mapped[list["ToolCallRow"]] = relationship(back_populates="turn_trace")


class ToolCallRow(Base):
    __tablename__ = "tool_calls"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    turn_trace_id: Mapped[UUID] = mapped_column(
        ForeignKey("turn_traces.id", ondelete="CASCADE"), index=True
    )
    tool_name: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    input_payload: Mapped[dict] = mapped_column("input", JSONB, nullable=False)
    output_payload: Mapped[dict | None] = mapped_column("output", JSONB)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)
    called_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    turn_trace: Mapped[TurnTrace] = relationship(back_populates="tool_calls")
