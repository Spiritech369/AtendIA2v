"""Operator dashboard — analytics (Phase 4 T42-T44, Block H).

Three endpoints, all tenant-scoped, all date-range-filtered via
optional `?from=` and `?to=` ISO dates:

* `GET /funnel` — plan_assigned / quoted / papeleria_completa counts
  derived from `conversation_state.extracted_data` JSONB.
* `GET /cost` — daily aggregates of `turn_traces.{nlu,composer,tool,vision}_cost_usd`.
* `GET /volume` — message volume by hour-of-day (heatmap data).
"""
from __future__ import annotations

from datetime import date, datetime, time, timezone
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import case, cast, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.api._auth_helpers import AuthUser
from atendia.api._deps import current_tenant_id, current_user
from atendia.db.models.conversation import Conversation, ConversationStateRow
from atendia.db.models.message import MessageRow
from atendia.db.models.turn_trace import TurnTrace
from atendia.db.session import get_db_session

router = APIRouter()


def _date_to_dt(d: date | None, *, end_of_day: bool = False) -> datetime | None:
    if d is None:
        return None
    return datetime.combine(d, time.max if end_of_day else time.min, tzinfo=timezone.utc)


# ---------- Funnel ----------


class FunnelResponse(BaseModel):
    total_conversations: int
    quoted: int
    plan_assigned: int
    papeleria_completa: int


@router.get("/funnel", response_model=FunnelResponse)
async def funnel(
    user: AuthUser = Depends(current_user),  # noqa: ARG001
    tenant_id: UUID = Depends(current_tenant_id),
    from_: date | None = Query(None, alias="from"),
    to: date | None = Query(None),
    session: AsyncSession = Depends(get_db_session),
) -> FunnelResponse:
    has_field = lambda key: ConversationStateRow.extracted_data[key].astext.is_not(None)  # noqa: E731
    bool_field = lambda key: cast(  # noqa: E731
        ConversationStateRow.extracted_data[key], JSONB
    ).astext.cast(__import__("sqlalchemy").Boolean)

    stmt = (
        select(
            func.count(Conversation.id.distinct()).label("total"),
            func.count(case((has_field("modelo_moto"), Conversation.id))).label("quoted"),
            func.count(case((has_field("plan_credito"), Conversation.id))).label(
                "plan_assigned"
            ),
            func.count(
                case(
                    (
                        ConversationStateRow.extracted_data["papeleria_completa"]
                        .astext.cast(__import__("sqlalchemy").Boolean)
                        .is_(True),
                        Conversation.id,
                    )
                )
            ).label("papeleria_completa"),
        )
        .select_from(Conversation)
        .join(
            ConversationStateRow,
            ConversationStateRow.conversation_id == Conversation.id,
        )
        .where(Conversation.tenant_id == tenant_id)
    )
    f = _date_to_dt(from_)
    t = _date_to_dt(to, end_of_day=True)
    if f is not None:
        stmt = stmt.where(Conversation.created_at >= f)
    if t is not None:
        stmt = stmt.where(Conversation.created_at <= t)

    row = (await session.execute(stmt)).one()
    return FunnelResponse(
        total_conversations=row.total,
        quoted=row.quoted,
        plan_assigned=row.plan_assigned,
        papeleria_completa=row.papeleria_completa,
    )


# ---------- Cost ----------


class CostDayPoint(BaseModel):
    day: date
    nlu_usd: Decimal
    composer_usd: Decimal
    tool_usd: Decimal
    vision_usd: Decimal
    total_usd: Decimal


class CostResponse(BaseModel):
    points: list[CostDayPoint]


@router.get("/cost", response_model=CostResponse)
async def cost(
    user: AuthUser = Depends(current_user),  # noqa: ARG001
    tenant_id: UUID = Depends(current_tenant_id),
    from_: date | None = Query(None, alias="from"),
    to: date | None = Query(None),
    session: AsyncSession = Depends(get_db_session),
) -> CostResponse:
    day_col = func.date_trunc("day", TurnTrace.created_at).label("day")
    stmt = (
        select(
            day_col,
            func.coalesce(func.sum(TurnTrace.nlu_cost_usd), 0).label("nlu_usd"),
            func.coalesce(func.sum(TurnTrace.composer_cost_usd), 0).label("composer_usd"),
            func.coalesce(func.sum(TurnTrace.tool_cost_usd), 0).label("tool_usd"),
            func.coalesce(func.sum(TurnTrace.vision_cost_usd), 0).label("vision_usd"),
        )
        .where(TurnTrace.tenant_id == tenant_id)
        .group_by(day_col)
        .order_by(day_col.asc())
    )
    f = _date_to_dt(from_)
    t = _date_to_dt(to, end_of_day=True)
    if f is not None:
        stmt = stmt.where(TurnTrace.created_at >= f)
    if t is not None:
        stmt = stmt.where(TurnTrace.created_at <= t)
    rows = (await session.execute(stmt)).all()
    points: list[CostDayPoint] = []
    for r in rows:
        nlu = Decimal(r.nlu_usd or 0)
        comp = Decimal(r.composer_usd or 0)
        tool = Decimal(r.tool_usd or 0)
        vision = Decimal(r.vision_usd or 0)
        points.append(
            CostDayPoint(
                day=r.day.date() if hasattr(r.day, "date") else r.day,
                nlu_usd=nlu,
                composer_usd=comp,
                tool_usd=tool,
                vision_usd=vision,
                total_usd=nlu + comp + tool + vision,
            )
        )
    return CostResponse(points=points)


# ---------- Volume / heatmap ----------


class VolumeBucket(BaseModel):
    hour: int
    inbound: int
    outbound: int


class VolumeResponse(BaseModel):
    buckets: list[VolumeBucket]


@router.get("/volume", response_model=VolumeResponse)
async def volume(
    user: AuthUser = Depends(current_user),  # noqa: ARG001
    tenant_id: UUID = Depends(current_tenant_id),
    from_: date | None = Query(None, alias="from"),
    to: date | None = Query(None),
    session: AsyncSession = Depends(get_db_session),
) -> VolumeResponse:
    hour_col = func.extract("hour", MessageRow.sent_at).label("hour")
    stmt = (
        select(
            hour_col,
            func.count(case((MessageRow.direction == "inbound", 1))).label("inbound"),
            func.count(case((MessageRow.direction == "outbound", 1))).label("outbound"),
        )
        .where(MessageRow.tenant_id == tenant_id)
        .group_by(hour_col)
        .order_by(hour_col.asc())
    )
    f = _date_to_dt(from_)
    t = _date_to_dt(to, end_of_day=True)
    if f is not None:
        stmt = stmt.where(MessageRow.sent_at >= f)
    if t is not None:
        stmt = stmt.where(MessageRow.sent_at <= t)
    rows = (await session.execute(stmt)).all()
    by_hour = {int(r.hour): (r.inbound, r.outbound) for r in rows}
    return VolumeResponse(
        buckets=[
            VolumeBucket(
                hour=h,
                inbound=by_hour.get(h, (0, 0))[0],
                outbound=by_hour.get(h, (0, 0))[1],
            )
            for h in range(24)
        ]
    )
