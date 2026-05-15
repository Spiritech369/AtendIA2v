"""Reports — manager-facing overview (one screen, four metrics).

Returns the four headline numbers the dueño-comprador wants to see at
a glance: how many conversations are coming in, how fast we respond,
how often we escalate to a human, and how leads flow through the
pipeline. Vertical-agnostic by construction — the funnel is built
from the tenant's own pipeline stages.

Single endpoint by design: the MVP is "open the page, see four
numbers". When operators ask for drill-down or filters, we add new
endpoints rather than parameterize this one.
"""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.api._auth_helpers import AuthUser
from atendia.api._deps import current_tenant_id, current_user
from atendia.db.models.conversation import Conversation
from atendia.db.models.lifecycle import HumanHandoff
from atendia.db.models.message import MessageRow
from atendia.db.models.tenant import Tenant
from atendia.db.models.tenant_config import TenantPipeline
from atendia.db.session import get_db_session

router = APIRouter()

WINDOW_DAYS = 30


class ConversationsCounts(BaseModel):
    today: int
    this_week: int  # Monday-anchored, tenant timezone
    this_month: int  # 1st of current month, tenant timezone


class FirstResponseStat(BaseModel):
    avg_seconds: float | None
    sample_size: int
    window_days: int


class HandoffStat(BaseModel):
    handoff_rate_pct: float
    total_conversations: int
    handed_off: int
    window_days: int


class FunnelStage(BaseModel):
    stage_id: str
    label: str
    current_count: int  # conversations currently AT this stage
    reached_count: int  # conversations AT this stage OR a later one (cumulative)
    conversion_pct: float | None  # reached_count / reached_count_of_first_stage


class ReportsOverview(BaseModel):
    conversations: ConversationsCounts
    first_response: FirstResponseStat
    handoff: HandoffStat
    pipeline_funnel: list[FunnelStage]
    tenant_timezone: str
    generated_at: datetime


async def _tenant_timezone(session: AsyncSession, tenant_id: UUID) -> str:
    tz = (
        await session.execute(select(Tenant.timezone).where(Tenant.id == tenant_id))
    ).scalar_one_or_none()
    return tz or "America/Mexico_City"


def _local_day_bounds(zone: ZoneInfo) -> tuple[datetime, datetime, datetime, datetime]:
    """Return (today_start_utc, week_start_utc, month_start_utc, window_start_utc)
    anchored to the tenant's timezone so "today" matches what the operator sees."""
    now_local = datetime.now(zone)
    today_local = now_local.date()
    today_start_local = datetime.combine(today_local, time.min, tzinfo=zone)
    today_start = today_start_local.astimezone(UTC)
    # ISO week — Monday is day 0. weekday() returns 0 for Monday.
    week_start_local = today_start_local - timedelta(days=today_local.weekday())
    week_start = week_start_local.astimezone(UTC)
    month_start_local = today_start_local.replace(day=1)
    month_start = month_start_local.astimezone(UTC)
    window_start = (today_start_local - timedelta(days=WINDOW_DAYS)).astimezone(UTC)
    return today_start, week_start, month_start, window_start


async def _conversation_counts(
    session: AsyncSession,
    tenant_id: UUID,
    *,
    today_start: datetime,
    week_start: datetime,
    month_start: datetime,
) -> ConversationsCounts:
    base = (
        select(func.count(Conversation.id))
        .select_from(Conversation)
        .where(
            Conversation.tenant_id == tenant_id,
            Conversation.deleted_at.is_(None),
        )
    )
    today = (await session.execute(base.where(Conversation.created_at >= today_start))).scalar_one()
    week = (await session.execute(base.where(Conversation.created_at >= week_start))).scalar_one()
    month = (await session.execute(base.where(Conversation.created_at >= month_start))).scalar_one()
    return ConversationsCounts(today=today, this_week=week, this_month=month)


async def _first_response(
    session: AsyncSession, tenant_id: UUID, *, window_start: datetime
) -> FirstResponseStat:
    """Time from first inbound to first subsequent outbound, per conversation,
    averaged. Conversations without an outbound response yet are excluded."""
    first_in_sub = (
        select(
            MessageRow.conversation_id.label("cid"),
            func.min(MessageRow.sent_at).label("first_in_at"),
        )
        .where(
            MessageRow.tenant_id == tenant_id,
            MessageRow.direction == "inbound",
            MessageRow.sent_at >= window_start,
        )
        .group_by(MessageRow.conversation_id)
        .subquery()
    )
    first_out_sub = (
        select(
            MessageRow.conversation_id.label("cid"),
            func.min(MessageRow.sent_at).label("first_out_at"),
        )
        .where(
            MessageRow.tenant_id == tenant_id,
            MessageRow.direction == "outbound",
            MessageRow.sent_at >= window_start,
        )
        .group_by(MessageRow.conversation_id)
        .subquery()
    )
    stmt = (
        select(
            func.avg(
                func.extract("epoch", first_out_sub.c.first_out_at - first_in_sub.c.first_in_at)
            ).label("avg_seconds"),
            func.count(first_in_sub.c.cid).label("sample"),
        )
        .select_from(first_in_sub)
        .join(first_out_sub, first_out_sub.c.cid == first_in_sub.c.cid)
        .where(first_out_sub.c.first_out_at >= first_in_sub.c.first_in_at)
    )
    row = (await session.execute(stmt)).one()
    avg_seconds = float(row.avg_seconds) if row.avg_seconds is not None else None
    return FirstResponseStat(
        avg_seconds=avg_seconds,
        sample_size=int(row.sample or 0),
        window_days=WINDOW_DAYS,
    )


async def _handoff_rate(
    session: AsyncSession, tenant_id: UUID, *, window_start: datetime
) -> HandoffStat:
    total = (
        await session.execute(
            select(func.count(Conversation.id))
            .select_from(Conversation)
            .where(
                Conversation.tenant_id == tenant_id,
                Conversation.deleted_at.is_(None),
                Conversation.created_at >= window_start,
            )
        )
    ).scalar_one()
    handed_off = (
        await session.execute(
            select(func.count(func.distinct(HumanHandoff.conversation_id))).where(
                HumanHandoff.tenant_id == tenant_id,
                HumanHandoff.requested_at >= window_start,
            )
        )
    ).scalar_one()
    pct = (handed_off / total * 100.0) if total > 0 else 0.0
    return HandoffStat(
        handoff_rate_pct=pct,
        total_conversations=total,
        handed_off=handed_off,
        window_days=WINDOW_DAYS,
    )


async def _pipeline_funnel(session: AsyncSession, tenant_id: UUID) -> list[FunnelStage]:
    """Project conversation counts onto the tenant's active pipeline stages.
    Builds a cumulative funnel: `reached` at stage N = conversations whose
    current_stage is N or any LATER stage in the pipeline's declared order."""
    pipeline = (
        await session.execute(
            select(TenantPipeline)
            .where(
                TenantPipeline.tenant_id == tenant_id,
                TenantPipeline.active.is_(True),
            )
            .order_by(TenantPipeline.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if pipeline is None:
        return []

    defn = pipeline.definition or {}
    raw_stages = defn.get("stages") or []
    stage_meta: list[tuple[str, str]] = []
    for s in raw_stages:
        if not isinstance(s, dict):
            continue
        sid = s.get("id")
        if not isinstance(sid, str):
            continue
        label = s.get("label") if isinstance(s.get("label"), str) else sid
        stage_meta.append((sid, label))

    if not stage_meta:
        return []

    counts_rows = (
        await session.execute(
            select(Conversation.current_stage, func.count(Conversation.id))
            .where(
                Conversation.tenant_id == tenant_id,
                Conversation.deleted_at.is_(None),
            )
            .group_by(Conversation.current_stage)
        )
    ).all()
    counts = {sid: cnt for sid, cnt in counts_rows}

    stage_counts = [(sid, label, counts.get(sid, 0)) for sid, label in stage_meta]
    cumulative_total = sum(c for _, _, c in stage_counts)
    if cumulative_total == 0:
        return [
            FunnelStage(
                stage_id=sid, label=label, current_count=0, reached_count=0, conversion_pct=None
            )
            for sid, label, _ in stage_counts
        ]

    out: list[FunnelStage] = []
    running = cumulative_total
    for sid, label, current in stage_counts:
        reached = running
        conversion = (reached / cumulative_total) * 100.0
        out.append(
            FunnelStage(
                stage_id=sid,
                label=label,
                current_count=current,
                reached_count=reached,
                conversion_pct=conversion,
            )
        )
        running -= current
    return out


@router.get("/overview", response_model=ReportsOverview)
async def get_reports_overview(
    user: AuthUser = Depends(current_user),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> ReportsOverview:
    timezone_str = await _tenant_timezone(session, tenant_id)
    zone = ZoneInfo(timezone_str)
    today_start, week_start, month_start, window_start = _local_day_bounds(zone)

    return ReportsOverview(
        conversations=await _conversation_counts(
            session,
            tenant_id,
            today_start=today_start,
            week_start=week_start,
            month_start=month_start,
        ),
        first_response=await _first_response(session, tenant_id, window_start=window_start),
        handoff=await _handoff_rate(session, tenant_id, window_start=window_start),
        pipeline_funnel=await _pipeline_funnel(session, tenant_id),
        tenant_timezone=timezone_str,
        generated_at=datetime.now(UTC),
    )
