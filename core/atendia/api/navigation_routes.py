"""Navigation badges — aggregated counts for the sidebar.

Single endpoint, 5 tenant-scoped counts + 1 user-scoped count, executed in
parallel via asyncio.gather. Polled by the frontend every 30s. Avoids 5
separate round-trips per tick.

The "overdue" threshold for handoffs is a project default (2h since
`requested_at`) since the schema has no dedicated SLA column.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.api._auth_helpers import AuthUser
from atendia.api._deps import current_tenant_id, current_user
from atendia.db.models.appointment import Appointment
from atendia.db.models.conversation import Conversation
from atendia.db.models.lifecycle import HumanHandoff
from atendia.db.models.notification import Notification
from atendia.db.models.turn_trace import TurnTrace
from atendia.db.session import get_db_session

router = APIRouter()

HANDOFF_OVERDUE_HOURS = 2


class NavigationBadges(BaseModel):
    conversations_open: int
    handoffs_open: int
    handoffs_overdue: int
    appointments_today: int
    ai_debug_warnings: int
    unread_notifications: int


@router.get("/badges", response_model=NavigationBadges)
async def get_navigation_badges(
    user: AuthUser = Depends(current_user),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> NavigationBadges:
    now = datetime.now(timezone.utc)
    overdue_threshold = now - timedelta(hours=HANDOFF_OVERDUE_HOURS)
    warnings_since = now - timedelta(hours=24)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + timedelta(days=1)

    # Sequential awaits: SQLAlchemy AsyncSession is not safe for concurrent
    # use (one cursor per session). 6 count queries on indexed columns is
    # ~50ms total — parallelism is not worth the session multiplication.
    async def _count(stmt) -> int:
        return (await session.execute(stmt)).scalar_one()

    conv_q = (
        select(func.count())
        .select_from(Conversation)
        .where(
            Conversation.tenant_id == tenant_id,
            Conversation.deleted_at.is_(None),
            Conversation.status != "resolved",
        )
    )
    handoffs_open_q = (
        select(func.count())
        .select_from(HumanHandoff)
        .where(
            HumanHandoff.tenant_id == tenant_id,
            HumanHandoff.status.in_(("open", "assigned")),
        )
    )
    handoffs_overdue_q = (
        select(func.count())
        .select_from(HumanHandoff)
        .where(
            HumanHandoff.tenant_id == tenant_id,
            HumanHandoff.status.in_(("open", "assigned")),
            HumanHandoff.requested_at < overdue_threshold,
        )
    )
    appointments_q = (
        select(func.count())
        .select_from(Appointment)
        .where(
            Appointment.tenant_id == tenant_id,
            Appointment.scheduled_at >= today_start,
            Appointment.scheduled_at < today_end,
            Appointment.status.in_(("scheduled", "confirmed", "pending")),
        )
    )
    warnings_q = (
        select(func.count())
        .select_from(TurnTrace)
        .where(
            TurnTrace.tenant_id == tenant_id,
            TurnTrace.errors.is_not(None),
            TurnTrace.created_at >= warnings_since,
        )
    )
    unread_q = (
        select(func.count())
        .select_from(Notification)
        .where(
            Notification.user_id == user.user_id,
            Notification.read.is_(False),
        )
    )

    conversations_open = await _count(conv_q)
    handoffs_open = await _count(handoffs_open_q)
    handoffs_overdue = await _count(handoffs_overdue_q)
    appointments_today = await _count(appointments_q)
    ai_debug_warnings = await _count(warnings_q)
    unread_notifications = await _count(unread_q)

    return NavigationBadges(
        conversations_open=conversations_open,
        handoffs_open=handoffs_open,
        handoffs_overdue=handoffs_overdue,
        appointments_today=appointments_today,
        ai_debug_warnings=ai_debug_warnings,
        unread_notifications=unread_notifications,
    )
