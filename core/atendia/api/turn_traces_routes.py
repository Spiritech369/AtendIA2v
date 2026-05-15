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
from sqlalchemy.orm import selectinload

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
    inbound_message_id: UUID | None
    # First 120 chars of inbound_text so operators can scan the list view
    # without opening every row. None when the turn had no inbound text
    # (image/audio adjuncts, system-triggered turns).
    inbound_preview: str | None
    flow_mode: str | None
    nlu_model: str | None
    composer_model: str | None
    total_cost_usd: Decimal
    total_latency_ms: int | None
    bot_paused: bool
    created_at: datetime


class TurnTraceListResponse(BaseModel):
    items: list[TurnTraceListItem]


class ToolCallOut(BaseModel):
    id: UUID
    tool_name: str
    input_payload: dict
    output_payload: dict | None
    latency_ms: int | None
    error: str | None
    called_at: datetime


class TurnTraceDetail(TurnTraceListItem):
    inbound_text: str | None
    # Migration 048 — DebugPanel observability. Cleaned/normalized form
    # of inbound_text after the runner's text-prep step (whitespace
    # collapse, NFKC, etc.). NULL on legacy rows seeded before the
    # runner instrumentation landed.
    inbound_text_cleaned: str | None
    nlu_input: dict | None
    nlu_output: dict | None
    nlu_tokens_in: int | None
    nlu_tokens_out: int | None
    nlu_cost_usd: Decimal | None
    nlu_latency_ms: int | None
    composer_input: dict | None
    composer_output: dict | None
    composer_tokens_in: int | None
    composer_tokens_out: int | None
    composer_cost_usd: Decimal | None
    composer_latency_ms: int | None
    # Migration 048 — DebugPanel observability. Resolved LLM provider
    # for the composer call (e.g. 'openai', 'anthropic'). NULL on
    # legacy rows.
    composer_provider: str | None
    vision_cost_usd: Decimal | None
    vision_latency_ms: int | None
    tool_cost_usd: Decimal | None
    state_before: dict | None
    state_after: dict | None
    stage_transition: str | None
    outbound_messages: list | None
    errors: list | None
    tool_calls: list[ToolCallOut]
    # Migration 045 — DebugPanel observability. NULL on legacy rows.
    router_trigger: str | None
    raw_llm_response: str | None
    agent_id: UUID | None
    kb_evidence: dict | None
    rules_evaluated: list | None


@router.get("", response_model=TurnTraceListResponse)
async def list_turn_traces(
    user: AuthUser = Depends(current_user),
    tenant_id: UUID = Depends(current_tenant_id),
    conversation_id: UUID | None = Query(None),
    flow_mode: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    session: AsyncSession = Depends(get_db_session),
) -> TurnTraceListResponse:
    """List turn traces.

    Two modes:

    * **Single-conversation** (legacy): pass ``conversation_id`` and the
      response is ordered by ``turn_number ASC`` (chronological inside
      the conversation).
    * **Cross-conversation explorer** (Sprint C.2 / T56): omit
      ``conversation_id`` and the response is ordered by ``created_at
      DESC`` across every conversation in the tenant — the operator's
      entry point when investigating recent runner activity without
      knowing which conversation to look at first. Optional
      ``flow_mode`` narrows the slice (e.g. only the SUPPORT-mode
      turns, useful when triaging a regression in one mode).
    """
    # Existence + tenant-scope check on the conversation. 404 (not 403)
    # if the operator tries to read a different tenant's traces.
    if conversation_id is not None:
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

    stmt = select(TurnTrace).where(TurnTrace.tenant_id == tenant_id)
    if conversation_id is not None:
        stmt = stmt.where(TurnTrace.conversation_id == conversation_id).order_by(
            TurnTrace.turn_number.asc()
        )
    else:
        # Cross-conversation: most recent activity first.
        stmt = stmt.order_by(TurnTrace.created_at.desc())
    if flow_mode is not None:
        stmt = stmt.where(TurnTrace.flow_mode == flow_mode)
    stmt = stmt.limit(limit)
    rows = (await session.execute(stmt)).scalars().all()

    return TurnTraceListResponse(
        items=[
            TurnTraceListItem(
                id=r.id,
                conversation_id=r.conversation_id,
                turn_number=r.turn_number,
                inbound_message_id=r.inbound_message_id,
                inbound_preview=(r.inbound_text[:120] if r.inbound_text else None),
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
    user: AuthUser = Depends(current_user),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> TurnTraceDetail:
    row = (
        await session.execute(
            select(TurnTrace)
            .options(selectinload(TurnTrace.tool_calls))
            .where(
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
        inbound_message_id=row.inbound_message_id,
        inbound_preview=(row.inbound_text[:120] if row.inbound_text else None),
        flow_mode=row.flow_mode,
        nlu_model=row.nlu_model,
        composer_model=row.composer_model,
        total_cost_usd=row.total_cost_usd,
        total_latency_ms=row.total_latency_ms,
        bot_paused=row.bot_paused,
        created_at=row.created_at,
        inbound_text=row.inbound_text,
        inbound_text_cleaned=row.inbound_text_cleaned,
        nlu_input=row.nlu_input,
        nlu_output=row.nlu_output,
        nlu_tokens_in=row.nlu_tokens_in,
        nlu_tokens_out=row.nlu_tokens_out,
        nlu_cost_usd=row.nlu_cost_usd,
        nlu_latency_ms=row.nlu_latency_ms,
        composer_input=row.composer_input,
        composer_output=row.composer_output,
        composer_tokens_in=row.composer_tokens_in,
        composer_tokens_out=row.composer_tokens_out,
        composer_cost_usd=row.composer_cost_usd,
        composer_latency_ms=row.composer_latency_ms,
        composer_provider=row.composer_provider,
        vision_cost_usd=row.vision_cost_usd,
        vision_latency_ms=row.vision_latency_ms,
        tool_cost_usd=row.tool_cost_usd,
        state_before=row.state_before,
        state_after=row.state_after,
        stage_transition=row.stage_transition,
        outbound_messages=row.outbound_messages,
        errors=row.errors,
        router_trigger=row.router_trigger,
        raw_llm_response=row.raw_llm_response,
        agent_id=row.agent_id,
        kb_evidence=row.kb_evidence,
        rules_evaluated=row.rules_evaluated,
        tool_calls=[
            ToolCallOut(
                id=tc.id,
                tool_name=tc.tool_name,
                input_payload=tc.input_payload,
                output_payload=tc.output_payload,
                latency_ms=tc.latency_ms,
                error=tc.error,
                called_at=tc.called_at,
            )
            for tc in row.tool_calls
        ],
    )
