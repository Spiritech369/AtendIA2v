from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.api._auth_helpers import AuthUser
from atendia.api._deps import current_tenant_id, current_user
from atendia.db.models.conversation import Conversation, ConversationStateRow
from atendia.db.models.customer import Customer
from atendia.db.models.message import MessageRow
from atendia.db.models.tenant_config import TenantPipeline
from atendia.db.session import get_db_session

router = APIRouter()


class PipelineConversationCard(BaseModel):
    id: UUID
    customer_id: UUID
    customer_name: str | None
    customer_phone: str
    last_message_text: str | None
    last_activity_at: datetime
    current_stage: str
    is_stale: bool


class StageGroup(BaseModel):
    stage_id: str
    stage_label: str
    total_count: int
    timeout_hours: int | None
    # ``True`` for the synthetic "orphan" group — conversations whose
    # ``current_stage`` is not in the active pipeline (e.g. the stage was
    # renamed or removed in config). Without this, those conversations
    # silently disappear from the board.
    is_orphan: bool = False
    conversations: list[PipelineConversationCard]


class PipelineBoardResponse(BaseModel):
    stages: list[StageGroup]


class PipelineAlertsResponse(BaseModel):
    items: list[PipelineConversationCard]


async def _active_pipeline(session: AsyncSession, tenant_id: UUID) -> dict:
    definition = (
        await session.execute(
            select(TenantPipeline.definition)
            .where(TenantPipeline.tenant_id == tenant_id, TenantPipeline.active.is_(True))
            .order_by(TenantPipeline.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if not definition:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no active pipeline")
    return definition


def _stage_defs(definition: dict) -> list[dict]:
    stages = definition.get("stages")
    if not isinstance(stages, list):
        return []
    return [s for s in stages if isinstance(s, dict) and isinstance(s.get("id"), str)]


async def _cards(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    stage_id: str | None,
    timeout_hours_by_stage: dict[str, int | None],
    limit: int,
    assigned_user_id: UUID | None = None,
    orphan_stage_ids: list[str] | None = None,
) -> list[PipelineConversationCard]:
    last_msg_sq = (
        select(
            MessageRow.conversation_id.label("cid"),
            MessageRow.text.label("text"),
            func.row_number()
            .over(partition_by=MessageRow.conversation_id, order_by=MessageRow.created_at.desc())
            .label("rn"),
        )
        .where(MessageRow.tenant_id == tenant_id)
        .subquery()
    )
    last_msg = select(last_msg_sq.c.cid, last_msg_sq.c.text).where(last_msg_sq.c.rn == 1).subquery()
    stmt = (
        select(
            Conversation.id,
            Conversation.customer_id,
            Customer.name.label("customer_name"),
            Customer.phone_e164.label("customer_phone"),
            last_msg.c.text.label("last_message_text"),
            Conversation.last_activity_at,
            Conversation.current_stage,
            ConversationStateRow.stage_entered_at,
        )
        .join(Customer, Customer.id == Conversation.customer_id)
        .join(ConversationStateRow, ConversationStateRow.conversation_id == Conversation.id)
        .outerjoin(last_msg, last_msg.c.cid == Conversation.id)
        .where(Conversation.tenant_id == tenant_id, Conversation.deleted_at.is_(None))
        .order_by(Conversation.last_activity_at.desc())
        .limit(limit)
    )
    if stage_id is not None:
        stmt = stmt.where(Conversation.current_stage == stage_id)
    if orphan_stage_ids is not None:
        # Synthetic "orphan" group: conversations whose current_stage isn't in
        # the active pipeline anymore. Empty list => no orphans possible.
        if not orphan_stage_ids:
            return []
        stmt = stmt.where(Conversation.current_stage.in_(orphan_stage_ids))
    if assigned_user_id is not None:
        stmt = stmt.where(Conversation.assigned_user_id == assigned_user_id)
    rows = (await session.execute(stmt)).all()
    now = datetime.now(UTC)
    items: list[PipelineConversationCard] = []
    for row in rows:
        timeout = timeout_hours_by_stage.get(row.current_stage)
        entered = row.stage_entered_at or row.last_activity_at
        is_stale = bool(timeout and entered and entered < now - timedelta(hours=timeout))
        items.append(
            PipelineConversationCard(
                id=row.id,
                customer_id=row.customer_id,
                customer_name=row.customer_name,
                customer_phone=row.customer_phone,
                last_message_text=row.last_message_text,
                last_activity_at=row.last_activity_at,
                current_stage=row.current_stage,
                is_stale=is_stale,
            )
        )
    return items


_BOARD_CARDS_PER_STAGE: int = 50


async def _board_cards_one_shot(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    timeout_hours_by_stage: dict[str, int | None],
    assigned_user_id: UUID | None,
    cards_per_stage: int,
) -> dict[str, list[PipelineConversationCard]]:
    """One window-function query returns up to ``cards_per_stage`` rows per
    ``current_stage`` with the last_message_text joined in. Replaces the
    previous per-stage loop (one round-trip per stage).
    """
    last_msg_sq = (
        select(
            MessageRow.conversation_id.label("cid"),
            MessageRow.text.label("text"),
            func.row_number()
            .over(
                partition_by=MessageRow.conversation_id,
                order_by=MessageRow.created_at.desc(),
            )
            .label("rn"),
        )
        .where(MessageRow.tenant_id == tenant_id)
        .subquery()
    )
    last_msg = (
        select(last_msg_sq.c.cid, last_msg_sq.c.text)
        .where(last_msg_sq.c.rn == 1)
        .subquery()
    )

    base_filters = [
        Conversation.tenant_id == tenant_id,
        Conversation.deleted_at.is_(None),
    ]
    if assigned_user_id is not None:
        base_filters.append(Conversation.assigned_user_id == assigned_user_id)

    # Window-function rank of conversations within each stage, newest first.
    inner = (
        select(
            Conversation.id.label("id"),
            Conversation.customer_id.label("customer_id"),
            Conversation.current_stage.label("current_stage"),
            Conversation.last_activity_at.label("last_activity_at"),
            ConversationStateRow.stage_entered_at.label("stage_entered_at"),
            Customer.name.label("customer_name"),
            Customer.phone_e164.label("customer_phone"),
            last_msg.c.text.label("last_message_text"),
            func.row_number()
            .over(
                partition_by=Conversation.current_stage,
                order_by=Conversation.last_activity_at.desc(),
            )
            .label("stage_rank"),
        )
        .select_from(Conversation)
        .join(Customer, Customer.id == Conversation.customer_id)
        .join(
            ConversationStateRow,
            ConversationStateRow.conversation_id == Conversation.id,
        )
        .outerjoin(last_msg, last_msg.c.cid == Conversation.id)
        .where(*base_filters)
        .subquery()
    )

    rows = (
        await session.execute(
            select(inner).where(inner.c.stage_rank <= cards_per_stage)
        )
    ).all()

    now = datetime.now(UTC)
    grouped: dict[str, list[PipelineConversationCard]] = {}
    for row in rows:
        timeout = timeout_hours_by_stage.get(row.current_stage)
        entered = row.stage_entered_at or row.last_activity_at
        is_stale = bool(timeout and entered and entered < now - timedelta(hours=timeout))
        grouped.setdefault(row.current_stage, []).append(
            PipelineConversationCard(
                id=row.id,
                customer_id=row.customer_id,
                customer_name=row.customer_name,
                customer_phone=row.customer_phone,
                last_message_text=row.last_message_text,
                last_activity_at=row.last_activity_at,
                current_stage=row.current_stage,
                is_stale=is_stale,
            )
        )
    return grouped


@router.get("/board", response_model=PipelineBoardResponse)
async def get_pipeline_board(
    user: AuthUser = Depends(current_user),
    tenant_id: UUID = Depends(current_tenant_id),
    assigned_user_id: UUID | None = Query(
        None,
        description="Filter to conversations assigned to this user",
    ),
    session: AsyncSession = Depends(get_db_session),
) -> PipelineBoardResponse:
    """Returns conversations grouped by active pipeline stage.

    Single window-function query gets every stage's top-50 cards in one
    round-trip. The synthetic ``orphan`` group surfaces conversations
    whose ``current_stage`` is no longer in the active pipeline so they
    don't disappear from the board.
    """
    definition = await _active_pipeline(session, tenant_id)
    stages = _stage_defs(definition)
    timeout_by_stage = {s["id"]: s.get("timeout_hours") for s in stages}
    active_stage_ids = {s["id"] for s in stages}

    count_rows = (
        await session.execute(
            select(
                Conversation.current_stage,
                func.count(Conversation.id).label("n"),
            )
            .where(
                Conversation.tenant_id == tenant_id,
                Conversation.deleted_at.is_(None),
                *(
                    [Conversation.assigned_user_id == assigned_user_id]
                    if assigned_user_id is not None
                    else []
                ),
            )
            .group_by(Conversation.current_stage)
        )
    ).all()
    counts_by_stage: dict[str, int] = {row.current_stage: row.n for row in count_rows}
    orphan_stage_ids = [
        sid for sid in counts_by_stage if sid not in active_stage_ids
    ]

    cards_by_stage = await _board_cards_one_shot(
        session,
        tenant_id=tenant_id,
        timeout_hours_by_stage=timeout_by_stage,
        assigned_user_id=assigned_user_id,
        cards_per_stage=_BOARD_CARDS_PER_STAGE,
    )

    groups: list[StageGroup] = [
        StageGroup(
            stage_id=stage["id"],
            stage_label=stage.get("label") or stage["id"],
            total_count=counts_by_stage.get(stage["id"], 0),
            timeout_hours=stage.get("timeout_hours"),
            conversations=cards_by_stage.get(stage["id"], []),
        )
        for stage in stages
    ]

    if orphan_stage_ids:
        orphan_total = sum(counts_by_stage[sid] for sid in orphan_stage_ids)
        orphan_cards: list[PipelineConversationCard] = []
        for sid in orphan_stage_ids:
            orphan_cards.extend(cards_by_stage.get(sid, []))
        # Re-sort orphan cards by last_activity_at desc (across stages).
        orphan_cards.sort(key=lambda c: c.last_activity_at, reverse=True)
        groups.append(
            StageGroup(
                stage_id="__orphan__",
                stage_label="Sin etapa activa",
                total_count=orphan_total,
                timeout_hours=None,
                is_orphan=True,
                conversations=orphan_cards[:_BOARD_CARDS_PER_STAGE],
            )
        )
    return PipelineBoardResponse(stages=groups)


@router.get("/board/{stage_id}", response_model=StageGroup)
async def get_pipeline_stage(
    stage_id: str,
    user: AuthUser = Depends(current_user),
    tenant_id: UUID = Depends(current_tenant_id),
    limit: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_db_session),
) -> StageGroup:
    definition = await _active_pipeline(session, tenant_id)
    stages = _stage_defs(definition)
    stage = next((s for s in stages if s["id"] == stage_id), None)
    if stage is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "stage not found")
    timeout_by_stage = {s["id"]: s.get("timeout_hours") for s in stages}
    total = (
        await session.execute(
            select(func.count())
            .select_from(Conversation)
            .where(
                Conversation.tenant_id == tenant_id,
                Conversation.deleted_at.is_(None),
                Conversation.current_stage == stage_id,
            )
        )
    ).scalar_one()
    return StageGroup(
        stage_id=stage_id,
        stage_label=stage.get("label") or stage_id,
        total_count=total,
        timeout_hours=stage.get("timeout_hours"),
        conversations=await _cards(
            session,
            tenant_id=tenant_id,
            stage_id=stage_id,
            timeout_hours_by_stage=timeout_by_stage,
            limit=limit,
        ),
    )


@router.get("/alerts", response_model=PipelineAlertsResponse)
async def get_pipeline_alerts(
    user: AuthUser = Depends(current_user),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> PipelineAlertsResponse:
    """Stale conversations across all active stages with non-zero
    ``timeout_hours``. Direct SQL filter — no Python-side post-filter, no
    last-message join, no 500-row materialisation.
    """
    definition = await _active_pipeline(session, tenant_id)
    stages = _stage_defs(definition)
    timeout_by_stage = {
        s["id"]: s.get("timeout_hours")
        for s in stages
        if s.get("timeout_hours")  # 0 / None means "never alert"
    }
    if not timeout_by_stage:
        return PipelineAlertsResponse(items=[])

    now = datetime.now(UTC)
    # OR per stage: stage = X AND stage_entered_at < now - Xh
    stale_predicates = [
        and_(
            Conversation.current_stage == sid,
            func.coalesce(
                ConversationStateRow.stage_entered_at,
                Conversation.last_activity_at,
            )
            < now - timedelta(hours=int(hours)),
        )
        for sid, hours in timeout_by_stage.items()
    ]
    stmt = (
        select(
            Conversation.id,
            Conversation.customer_id,
            Conversation.current_stage,
            Conversation.last_activity_at,
            Customer.name.label("customer_name"),
            Customer.phone_e164.label("customer_phone"),
        )
        .select_from(Conversation)
        .join(Customer, Customer.id == Conversation.customer_id)
        .join(
            ConversationStateRow,
            ConversationStateRow.conversation_id == Conversation.id,
        )
        .where(
            Conversation.tenant_id == tenant_id,
            Conversation.deleted_at.is_(None),
            or_(*stale_predicates),
        )
        .order_by(Conversation.last_activity_at.asc())
        .limit(200)
    )
    rows = (await session.execute(stmt)).all()
    items = [
        PipelineConversationCard(
            id=row.id,
            customer_id=row.customer_id,
            customer_name=row.customer_name,
            customer_phone=row.customer_phone,
            last_message_text=None,
            last_activity_at=row.last_activity_at,
            current_stage=row.current_stage,
            is_stale=True,
        )
        for row in rows
    ]
    return PipelineAlertsResponse(items=items)
