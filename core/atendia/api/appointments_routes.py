from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.api._audit import emit_admin_event
from atendia.api._auth_helpers import AuthUser
from atendia.api._deps import current_tenant_id, current_user
from atendia.db.models.appointment import Appointment
from atendia.db.models.conversation import Conversation
from atendia.db.models.customer import Customer
from atendia.db.session import get_db_session

router = APIRouter()

APPOINTMENT_STATUSES = {"scheduled", "completed", "cancelled", "no_show"}

# Window in which two appointments for the same customer are flagged as
# overlapping. Conflicts are returned to the caller as warnings — operators
# can still confirm; we don't block the create.
APPOINTMENT_CONFLICT_WINDOW = timedelta(minutes=30)


class AppointmentItem(BaseModel):
    id: UUID
    customer_id: UUID
    customer_name: str | None
    customer_phone: str
    conversation_id: UUID | None
    scheduled_at: datetime
    service: str
    status: str
    notes: str | None
    created_by_type: str
    created_at: datetime


class AppointmentListResponse(BaseModel):
    items: list[AppointmentItem]
    total: int


class AppointmentConflictItem(BaseModel):
    id: UUID
    scheduled_at: datetime
    service: str
    status: str


class AppointmentCreateResponse(BaseModel):
    """``conflicts`` is non-empty when the new appointment overlaps with
    existing ones for the same customer (within ``APPOINTMENT_CONFLICT_WINDOW``).
    The frontend can warn the operator; the create itself is not blocked."""

    appointment: AppointmentItem
    conflicts: list[AppointmentConflictItem] = []


class AppointmentCreate(BaseModel):
    customer_id: UUID
    conversation_id: UUID | None = None
    scheduled_at: datetime
    service: str = Field(min_length=1, max_length=200)
    notes: str | None = Field(default=None, max_length=5000)

    @field_validator("scheduled_at")
    @classmethod
    def _must_be_tz_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("scheduled_at must include timezone")
        return value


class AppointmentPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scheduled_at: datetime | None = None
    service: str | None = Field(default=None, min_length=1, max_length=200)
    status: str | None = None
    notes: str | None = Field(default=None, max_length=5000)

    @field_validator("scheduled_at")
    @classmethod
    def _patch_must_be_tz_aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("scheduled_at must include timezone")
        return value

    @field_validator("status")
    @classmethod
    def _valid_status(cls, value: str | None) -> str | None:
        if value is not None and value not in APPOINTMENT_STATUSES:
            raise ValueError("invalid appointment status")
        return value


async def _assert_customer(
    session: AsyncSession, *, tenant_id: UUID, customer_id: UUID
) -> None:
    exists = (
        await session.execute(
            select(Customer.id).where(Customer.id == customer_id, Customer.tenant_id == tenant_id)
        )
    ).scalar_one_or_none()
    if exists is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "customer not found")


async def _assert_conversation(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    conversation_id: UUID | None,
    customer_id: UUID,
) -> None:
    if conversation_id is None:
        return
    exists = (
        await session.execute(
            select(Conversation.id).where(
                Conversation.id == conversation_id,
                Conversation.tenant_id == tenant_id,
                Conversation.customer_id == customer_id,
                Conversation.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if exists is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "conversation not found")


def _item(row) -> AppointmentItem:
    return AppointmentItem(
        id=row.id,
        customer_id=row.customer_id,
        customer_name=row.customer_name,
        customer_phone=row.customer_phone,
        conversation_id=row.conversation_id,
        scheduled_at=row.scheduled_at,
        service=row.service,
        status=row.status,
        notes=row.notes,
        created_by_type=row.created_by_type,
        created_at=row.created_at,
    )


async def _get_item(
    session: AsyncSession, *, tenant_id: UUID, appointment_id: UUID
) -> AppointmentItem:
    row = (
        await session.execute(
            select(
                Appointment.id,
                Appointment.customer_id,
                Customer.name.label("customer_name"),
                Customer.phone_e164.label("customer_phone"),
                Appointment.conversation_id,
                Appointment.scheduled_at,
                Appointment.service,
                Appointment.status,
                Appointment.notes,
                Appointment.created_by_type,
                Appointment.created_at,
            )
            .join(Customer, Customer.id == Appointment.customer_id)
            .where(
                Appointment.id == appointment_id,
                Appointment.tenant_id == tenant_id,
                Appointment.deleted_at.is_(None),
            )
        )
    ).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "appointment not found")
    return _item(row)


@router.get("", response_model=AppointmentListResponse)
async def list_appointments(
    user: AuthUser = Depends(current_user),
    tenant_id: UUID = Depends(current_tenant_id),
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    customer_id: UUID | None = Query(None),
    appointment_status: str | None = Query(None, alias="status"),
    limit: int = Query(100, ge=1, le=300),
    session: AsyncSession = Depends(get_db_session),
) -> AppointmentListResponse:
    stmt = (
        select(
            Appointment.id,
            Appointment.customer_id,
            Customer.name.label("customer_name"),
            Customer.phone_e164.label("customer_phone"),
            Appointment.conversation_id,
            Appointment.scheduled_at,
            Appointment.service,
            Appointment.status,
            Appointment.notes,
            Appointment.created_by_type,
            Appointment.created_at,
        )
        .join(Customer, Customer.id == Appointment.customer_id)
        .where(Appointment.tenant_id == tenant_id, Appointment.deleted_at.is_(None))
        .order_by(Appointment.scheduled_at.asc())
        .limit(limit)
    )
    if date_from is not None:
        stmt = stmt.where(Appointment.scheduled_at >= date_from)
    if date_to is not None:
        stmt = stmt.where(Appointment.scheduled_at < date_to)
    if customer_id is not None:
        stmt = stmt.where(Appointment.customer_id == customer_id)
    if appointment_status is not None:
        if appointment_status not in APPOINTMENT_STATUSES:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid appointment status")
        stmt = stmt.where(Appointment.status == appointment_status)

    rows = (await session.execute(stmt)).all()
    # Total honors the same filters but without the limit, so the UI can
    # show "X of Y citas filtradas".
    count_stmt = (
        select(func.count())
        .select_from(Appointment)
        .where(Appointment.tenant_id == tenant_id, Appointment.deleted_at.is_(None))
    )
    if date_from is not None:
        count_stmt = count_stmt.where(Appointment.scheduled_at >= date_from)
    if date_to is not None:
        count_stmt = count_stmt.where(Appointment.scheduled_at < date_to)
    if customer_id is not None:
        count_stmt = count_stmt.where(Appointment.customer_id == customer_id)
    if appointment_status is not None:
        count_stmt = count_stmt.where(Appointment.status == appointment_status)
    total = (await session.execute(count_stmt)).scalar_one()
    return AppointmentListResponse(items=[_item(row) for row in rows], total=total)


async def _find_conflicts(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    customer_id: UUID,
    scheduled_at: datetime,
    exclude_id: UUID | None = None,
) -> list[AppointmentConflictItem]:
    """Same-customer appointments within the conflict window. ``exclude_id``
    skips the row being patched so it doesn't conflict with itself."""
    lower = scheduled_at - APPOINTMENT_CONFLICT_WINDOW
    upper = scheduled_at + APPOINTMENT_CONFLICT_WINDOW
    stmt = (
        select(
            Appointment.id,
            Appointment.scheduled_at,
            Appointment.service,
            Appointment.status,
        )
        .where(
            Appointment.tenant_id == tenant_id,
            Appointment.customer_id == customer_id,
            Appointment.deleted_at.is_(None),
            Appointment.status == "scheduled",
            Appointment.scheduled_at >= lower,
            Appointment.scheduled_at <= upper,
        )
    )
    if exclude_id is not None:
        stmt = stmt.where(Appointment.id != exclude_id)
    return [
        AppointmentConflictItem(
            id=row.id,
            scheduled_at=row.scheduled_at,
            service=row.service,
            status=row.status,
        )
        for row in (await session.execute(stmt)).all()
    ]


@router.post("", response_model=AppointmentCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_appointment(
    body: AppointmentCreate,
    user: AuthUser = Depends(current_user),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> AppointmentCreateResponse:
    await _assert_customer(session, tenant_id=tenant_id, customer_id=body.customer_id)
    await _assert_conversation(
        session,
        tenant_id=tenant_id,
        conversation_id=body.conversation_id,
        customer_id=body.customer_id,
    )
    scheduled_utc = body.scheduled_at.astimezone(UTC)
    conflicts = await _find_conflicts(
        session,
        tenant_id=tenant_id,
        customer_id=body.customer_id,
        scheduled_at=scheduled_utc,
    )
    appt = Appointment(
        tenant_id=tenant_id,
        customer_id=body.customer_id,
        conversation_id=body.conversation_id,
        scheduled_at=scheduled_utc,
        service=body.service.strip(),
        notes=body.notes,
        created_by_id=user.user_id,
        created_by_type="user",
    )
    session.add(appt)
    await session.flush()
    await emit_admin_event(
        session,
        tenant_id=tenant_id,
        actor_user_id=user.user_id,
        action="appointment.created",
        payload={
            "appointment_id": str(appt.id),
            "customer_id": str(body.customer_id),
            "scheduled_at": scheduled_utc.isoformat(),
            "service": appt.service,
            "had_conflicts": len(conflicts) > 0,
        },
    )
    await session.commit()
    item = await _get_item(session, tenant_id=tenant_id, appointment_id=appt.id)
    return AppointmentCreateResponse(appointment=item, conflicts=conflicts)


@router.patch("/{appointment_id}", response_model=AppointmentItem)
async def patch_appointment(
    appointment_id: UUID,
    body: AppointmentPatch,
    user: AuthUser = Depends(current_user),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> AppointmentItem:
    appt = (
        await session.execute(
            select(Appointment).where(
                Appointment.id == appointment_id,
                Appointment.tenant_id == tenant_id,
                Appointment.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if appt is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "appointment not found")

    values = body.model_dump(exclude_unset=True)
    if "scheduled_at" in values and values["scheduled_at"] is not None:
        values["scheduled_at"] = values["scheduled_at"].astimezone(UTC)
    if "service" in values and values["service"] is not None:
        values["service"] = values["service"].strip()
    if not values:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "no fields to update")
    values["updated_at"] = datetime.now(UTC)

    await session.execute(update(Appointment).where(Appointment.id == appointment_id).values(**values))
    await emit_admin_event(
        session,
        tenant_id=tenant_id,
        actor_user_id=user.user_id,
        action="appointment.patched",
        payload={
            "appointment_id": str(appointment_id),
            "fields": sorted(k for k in values if k != "updated_at"),
        },
    )
    await session.commit()
    return await _get_item(session, tenant_id=tenant_id, appointment_id=appointment_id)


@router.delete("/{appointment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_appointment(
    appointment_id: UUID,
    user: AuthUser = Depends(current_user),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> None:
    result = await session.execute(
        update(Appointment)
        .where(
            Appointment.id == appointment_id,
            Appointment.tenant_id == tenant_id,
            Appointment.deleted_at.is_(None),
        )
        .values(deleted_at=datetime.now(UTC), updated_at=datetime.now(UTC))
    )
    if result.rowcount == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "appointment not found")
    await emit_admin_event(
        session,
        tenant_id=tenant_id,
        actor_user_id=user.user_id,
        action="appointment.deleted",
        payload={"appointment_id": str(appointment_id)},
    )
    await session.commit()
