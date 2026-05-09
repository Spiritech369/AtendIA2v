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
from atendia.db.models.appointment import Appointment
from atendia.db.models.conversation import Conversation
from atendia.db.models.customer import Customer
from atendia.db.models.message import MessageRow
from atendia.db.models.tenant import Tenant
from atendia.db.session import get_db_session

router = APIRouter()


class DashboardAppointment(BaseModel):
    id: UUID
    customer_id: UUID
    customer_name: str | None
    customer_phone: str
    scheduled_at: datetime
    service: str
    status: str


class RecentConversation(BaseModel):
    id: UUID
    customer_id: UUID
    customer_name: str | None
    customer_phone: str
    current_stage: str
    last_activity_at: datetime
    unread_count: int


class DayBucket(BaseModel):
    date: str
    inbound: int
    outbound: int


class DashboardSummary(BaseModel):
    total_customers: int
    conversations_today: int
    active_conversations: int
    unanswered_conversations: int
    todays_appointments: list[DashboardAppointment]
    recent_conversations: list[RecentConversation]
    activity_chart: list[DayBucket]


async def _tenant_day_bounds(session: AsyncSession, tenant_id: UUID) -> tuple[datetime, datetime, str]:
    timezone = (
        await session.execute(select(Tenant.timezone).where(Tenant.id == tenant_id))
    ).scalar_one_or_none() or "America/Mexico_City"
    zone = ZoneInfo(timezone)
    today = datetime.now(zone).date()
    start = datetime.combine(today, time.min, tzinfo=zone).astimezone(UTC)
    end = (datetime.combine(today, time.min, tzinfo=zone) + timedelta(days=1)).astimezone(UTC)
    return start, end, timezone


@router.get("/summary", response_model=DashboardSummary)
async def get_dashboard_summary(
    user: AuthUser = Depends(current_user),  # noqa: ARG001
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> DashboardSummary:
    start_utc, end_utc, _timezone = await _tenant_day_bounds(session, tenant_id)
    seven_days = start_utc - timedelta(days=6)

    total_customers = (
        await session.execute(select(func.count()).select_from(Customer).where(Customer.tenant_id == tenant_id))
    ).scalar_one()
    conversations_today = (
        await session.execute(
            select(func.count())
            .select_from(Conversation)
            .where(
                Conversation.tenant_id == tenant_id,
                Conversation.deleted_at.is_(None),
                Conversation.created_at >= start_utc,
                Conversation.created_at < end_utc,
            )
        )
    ).scalar_one()
    active_conversations = (
        await session.execute(
            select(func.count())
            .select_from(Conversation)
            .where(
                Conversation.tenant_id == tenant_id,
                Conversation.deleted_at.is_(None),
                Conversation.status == "active",
            )
        )
    ).scalar_one()
    unanswered_conversations = (
        await session.execute(
            select(func.count())
            .select_from(Conversation)
            .where(
                Conversation.tenant_id == tenant_id,
                Conversation.deleted_at.is_(None),
                Conversation.unread_count > 0,
            )
        )
    ).scalar_one()

    appt_rows = (
        await session.execute(
            select(
                Appointment.id,
                Appointment.customer_id,
                Customer.name.label("customer_name"),
                Customer.phone_e164.label("customer_phone"),
                Appointment.scheduled_at,
                Appointment.service,
                Appointment.status,
            )
            .join(Customer, Customer.id == Appointment.customer_id)
            .where(
                Appointment.tenant_id == tenant_id,
                Appointment.deleted_at.is_(None),
                Appointment.scheduled_at >= start_utc,
                Appointment.scheduled_at < end_utc,
            )
            .order_by(Appointment.scheduled_at.asc())
            .limit(10)
        )
    ).all()

    recent_rows = (
        await session.execute(
            select(
                Conversation.id,
                Conversation.customer_id,
                Customer.name.label("customer_name"),
                Customer.phone_e164.label("customer_phone"),
                Conversation.current_stage,
                Conversation.last_activity_at,
                Conversation.unread_count,
            )
            .join(Customer, Customer.id == Conversation.customer_id)
            .where(Conversation.tenant_id == tenant_id, Conversation.deleted_at.is_(None))
            .order_by(Conversation.last_activity_at.desc())
            .limit(10)
        )
    ).all()

    activity_rows = (
        await session.execute(
            select(
                func.date_trunc("day", MessageRow.sent_at).label("day"),
                func.count().filter(MessageRow.direction == "inbound").label("inbound"),
                func.count().filter(MessageRow.direction == "outbound").label("outbound"),
            )
            .where(MessageRow.tenant_id == tenant_id, MessageRow.sent_at >= seven_days)
            .group_by("day")
            .order_by("day")
        )
    ).all()
    by_day = {
        row.day.date().isoformat(): DayBucket(
            date=row.day.date().isoformat(),
            inbound=row.inbound,
            outbound=row.outbound,
        )
        for row in activity_rows
    }
    buckets: list[DayBucket] = []
    for i in range(7):
        day = (start_utc + timedelta(days=i - 6)).date().isoformat()
        buckets.append(by_day.get(day, DayBucket(date=day, inbound=0, outbound=0)))

    return DashboardSummary(
        total_customers=total_customers,
        conversations_today=conversations_today,
        active_conversations=active_conversations,
        unanswered_conversations=unanswered_conversations,
        todays_appointments=[DashboardAppointment(**row._mapping) for row in appt_rows],
        recent_conversations=[RecentConversation(**row._mapping) for row in recent_rows],
        activity_chart=buckets,
    )
