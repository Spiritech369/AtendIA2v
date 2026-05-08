"""Operator dashboard — turn-trace inspector (Phase 4 T34-T35, Block F).

Two endpoints:
* `GET /api/v1/turn-traces?conversation_id=...&from=...&to=...` — paginated
  list, NO payloads (just metadata for the table).
* `GET /api/v1/turn-traces/:id` — full row including nlu_input/output,
  composer_input/output, state_before/after, outbound_messages.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.api._auth_helpers import AuthUser
from atendia.api._deps import current_tenant_id, current_user
from atendia.db.models.conversation import Conversation
from atendia.db.models.turn_trace import TurnTrace
from atendia.db.session import get_db_session

router = APIRouter()


class TurnTraceListItem(BaseModel):
    id: UUID
    conversation_id: UUID
    turn_number: int
    flow_mode: str | None
    nlu_model: str | None
    composer_model: str | None
    total_cost_usd: Decimal
    total_latency_ms: int | None
    bot_paused: bool
    created_at: datetime


class TurnTraceListResponse(BaseModel):
    items: list[TurnTraceListItem]


class TurnTraceDetail(TurnTraceListItem):
    inbound_text: str | None
    nlu_input: dict | None
    nlu_output: dict | None
    composer_input: dict | None
    composer_output: dict | None
    state_before: dict | None
    state_after: dict | None
    outbound_messages: list | None
    stage_transition: str | None
    errors: list | None
    nlu_cost_usd: Decimal | None
    composer_cost_usd: Decimal | None
    tool_cost_usd: Decimal | None
    vision_cost_usd: Decimal | None


@router.get("", response_model=TurnTraceListResponse)
async def list_turn_traces(
    conversation_id: UUID = Query(...),
    user: AuthUser = Depends(current_user),  # noqa: ARG001
    tenant_id: UUID = Depends(current_tenant_id),
    limit: int = Query(100, ge=1, le=500),
    session: AsyncSession = Depends(get_db_session),
) -> TurnTraceListResponse:
    # Existence + tenant-scope check on the conversation. 404 (not 403)
    # if the operator tries to read a different tenant's traces.
    own = (
        await session.execute(
            select(Conversation.id).where(
                Conversation.id == conversation_id,
                Conversation.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if own is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "conversation not found")

    rows = (
        await session.execute(
            select(TurnTrace)
            .where(TurnTrace.conversation_id == conversation_id)
            .order_by(TurnTrace.turn_number.asc())
            .limit(limit)
        )
    ).scalars().all()

    return TurnTraceListResponse(
        items=[
            TurnTraceListItem(
                id=r.id,
                conversation_id=r.conversation_id,
                turn_number=r.turn_number,
                flow_mode=r.flow_mode,
                nlu_model=r.nlu_model,
                composer_model=r.composer_model,
                total_cost_usd=r.total_cost_usd,
                total_latency_ms=r.total_latency_ms,
                bot_paused=r.bot_paused,
                created_at=r.created_at,
            )
            for r in rows
        ]
    )


@router.get("/{trace_id}", response_model=TurnTraceDetail)
async def get_turn_trace(
    trace_id: UUID,
    user: AuthUser = Depends(current_user),  # noqa: ARG001
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> TurnTraceDetail:
    row = (
        await session.execute(
            select(TurnTrace).where(
                TurnTrace.id == trace_id,
                TurnTrace.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "trace not found")
    return TurnTraceDetail(
        id=row.id,
        conversation_id=row.conversation_id,
        turn_number=row.turn_number,
        flow_mode=row.flow_mode,
        nlu_model=row.nlu_model,
        composer_model=row.composer_model,
        total_cost_usd=row.total_cost_usd,
        total_latency_ms=row.total_latency_ms,
        bot_paused=row.bot_paused,
        created_at=row.created_at,
        inbound_text=row.inbound_text,
        nlu_input=row.nlu_input,
        nlu_output=row.nlu_output,
        composer_input=row.composer_input,
        composer_output=row.composer_output,
        state_before=row.state_before,
        state_after=row.state_after,
        outbound_messages=row.outbound_messages,
        stage_transition=row.stage_transition,
        errors=row.errors,
        nlu_cost_usd=row.nlu_cost_usd,
        composer_cost_usd=row.composer_cost_usd,
        tool_cost_usd=row.tool_cost_usd,
        vision_cost_usd=row.vision_cost_usd,
    )
