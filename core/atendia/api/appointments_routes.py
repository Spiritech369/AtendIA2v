from __future__ import annotations

import re
from collections import defaultdict
from datetime import UTC, datetime, time, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.api._audit import emit_admin_event
from atendia.api._auth_helpers import AuthUser
from atendia.api._deps import (
    current_tenant_id,
    current_user,
    get_advisor_provider,
    get_messaging_provider,
    get_vehicle_provider,
    require_tenant_admin,
)
from atendia.db.models.advisor import Advisor, Vehicle
from atendia.db.models.appointment import Appointment
from atendia.db.models.conversation import Conversation
from atendia.db.models.customer import Customer
from atendia.db.session import get_db_session
from atendia.providers.advisors import AdvisorProvider
from atendia.providers.messaging import MessageActionProvider
from atendia.providers.vehicles import VehicleProvider

router = APIRouter()

APPOINTMENT_STATUSES = {
    "scheduled",
    "confirmed",
    "arrived",
    "completed",
    "cancelled",
    "no_show",
    "rescheduled",
}
ACTIVE_STATUSES = {"scheduled", "confirmed", "arrived", "rescheduled"}
APPOINTMENT_TYPES = {
    "test_drive",
    "quote",
    "documents",
    "delivery",
    "follow_up",
    "financing",
    "call",
}
APPOINTMENT_CONFLICT_WINDOW = timedelta(minutes=30)
DEFAULT_TIMEZONE = "America/Mexico_City"
WORKDAY_START = time(8, 0)
WORKDAY_END = time(20, 0)

TYPE_LABELS = {
    "test_drive": "Prueba de manejo",
    "quote": "Cotización",
    "documents": "Documentos",
    "delivery": "Entrega",
    "follow_up": "Seguimiento",
    "financing": "Financiamiento",
    "call": "Llamada",
}

STATUS_TIMESTAMPS = {
    "confirmed": "confirmed_at",
    "arrived": "arrived_at",
    "completed": "completed_at",
    "cancelled": "cancelled_at",
    "no_show": "no_show_at",
}


class AppointmentItem(BaseModel):
    id: UUID
    customer_id: UUID
    customer_name: str | None
    customer_phone: str
    conversation_id: UUID | None
    scheduled_at: datetime
    ends_at: datetime | None
    appointment_type: str
    service: str
    status: str
    notes: str | None
    timezone: str
    source: str
    advisor_id: str | None
    advisor_name: str | None
    vehicle_id: str | None
    vehicle_label: str | None
    ai_confidence: float | None
    risk_score: int
    risk_level: str
    risk_reasons: list[dict]
    recommended_actions: list[dict]
    credit_plan: str | None
    down_payment_amount: int | None
    down_payment_confirmed: bool
    documents_complete: bool
    last_customer_reply_at: datetime | None
    confirmed_at: datetime | None
    arrived_at: datetime | None
    completed_at: datetime | None
    cancelled_at: datetime | None
    no_show_at: datetime | None
    reminder_status: str
    reminder_last_sent_at: datetime | None
    action_log: list[dict]
    created_by_type: str
    created_at: datetime
    updated_at: datetime
    conflict_count: int = 0


class AppointmentListResponse(BaseModel):
    items: list[AppointmentItem]
    total: int


class AppointmentConflictItem(BaseModel):
    id: UUID
    scheduled_at: datetime
    service: str
    status: str


class AppointmentCreateResponse(BaseModel):
    appointment: AppointmentItem
    conflicts: list[AppointmentConflictItem] = []


class AppointmentCreate(BaseModel):
    customer_id: UUID
    conversation_id: UUID | None = None
    scheduled_at: datetime
    ends_at: datetime | None = None
    appointment_type: str = "follow_up"
    service: str = Field(min_length=1, max_length=200)
    notes: str | None = Field(default=None, max_length=5000)
    timezone: str = DEFAULT_TIMEZONE
    source: str = "manual"
    advisor_id: str | None = Field(default=None, max_length=80)
    advisor_name: str | None = Field(default=None, max_length=160)
    vehicle_id: str | None = Field(default=None, max_length=80)
    vehicle_label: str | None = Field(default=None, max_length=160)
    ai_confidence: float | None = Field(default=None, ge=0, le=1)
    credit_plan: str | None = Field(default=None, max_length=120)
    down_payment_amount: int | None = Field(default=None, ge=0)
    down_payment_confirmed: bool = False
    documents_complete: bool = False
    last_customer_reply_at: datetime | None = None

    @field_validator("scheduled_at", "ends_at", "last_customer_reply_at")
    @classmethod
    def _must_be_tz_aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("datetime must include timezone")
        return value

    @field_validator("appointment_type")
    @classmethod
    def _valid_type(cls, value: str) -> str:
        if value not in APPOINTMENT_TYPES:
            raise ValueError("invalid appointment type")
        return value


class AppointmentPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scheduled_at: datetime | None = None
    ends_at: datetime | None = None
    appointment_type: str | None = None
    service: str | None = Field(default=None, min_length=1, max_length=200)
    status: str | None = None
    notes: str | None = Field(default=None, max_length=5000)
    timezone: str | None = None
    source: str | None = None
    advisor_id: str | None = Field(default=None, max_length=80)
    advisor_name: str | None = Field(default=None, max_length=160)
    vehicle_id: str | None = Field(default=None, max_length=80)
    vehicle_label: str | None = Field(default=None, max_length=160)
    ai_confidence: float | None = Field(default=None, ge=0, le=1)
    credit_plan: str | None = Field(default=None, max_length=120)
    down_payment_amount: int | None = Field(default=None, ge=0)
    down_payment_confirmed: bool | None = None
    documents_complete: bool | None = None
    last_customer_reply_at: datetime | None = None

    @field_validator("scheduled_at", "ends_at", "last_customer_reply_at")
    @classmethod
    def _patch_must_be_tz_aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("datetime must include timezone")
        return value

    @field_validator("status")
    @classmethod
    def _valid_status(cls, value: str | None) -> str | None:
        if value is not None and value not in APPOINTMENT_STATUSES:
            raise ValueError("invalid appointment status")
        return value

    @field_validator("appointment_type")
    @classmethod
    def _patch_valid_type(cls, value: str | None) -> str | None:
        if value is not None and value not in APPOINTMENT_TYPES:
            raise ValueError("invalid appointment type")
        return value


class ParseNaturalBody(BaseModel):
    text: str = Field(min_length=1, max_length=1000)
    timezone: str = DEFAULT_TIMEZONE
    now: datetime | None = None


class ParseNaturalResponse(BaseModel):
    understood: bool
    confidence: float
    date: str | None
    time: str | None
    appointment_type: str
    service: str
    customer_name: str | None
    customer_phone: str | None
    vehicle_label: str | None
    advisor_name: str | None
    down_payment_amount: int | None
    scheduled_at: datetime | None
    ends_at: datetime | None
    summary: str
    missing_fields: list[str]


class RescheduleBody(BaseModel):
    scheduled_at: datetime
    ends_at: datetime | None = None

    @field_validator("scheduled_at", "ends_at")
    @classmethod
    def _aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("datetime must include timezone")
        return value


class ChangeAdvisorBody(BaseModel):
    advisor_id: str | None = None
    advisor_name: str = Field(min_length=1, max_length=160)


class ChangeVehicleBody(BaseModel):
    vehicle_id: str | None = None
    vehicle_label: str = Field(min_length=1, max_length=160)


class FollowUpBody(BaseModel):
    title: str = Field(default="Seguimiento posterior a cita", max_length=160)
    due_at: datetime | None = None


def _type_label(value: str) -> str:
    return TYPE_LABELS.get(value, value)


def _duration_for(kind: str) -> timedelta:
    if kind == "call":
        return timedelta(minutes=30)
    if kind == "delivery":
        return timedelta(minutes=45)
    if kind == "documents":
        return timedelta(minutes=30)
    return timedelta(minutes=45)


def _end_for(appt: Appointment) -> datetime:
    return appt.ends_at or appt.scheduled_at + _duration_for(appt.appointment_type)


def _as_tz(value: datetime, timezone: str) -> datetime:
    return value.astimezone(ZoneInfo(timezone))


def _risk_level(score: int) -> str:
    if score >= 81:
        return "critical"
    if score >= 61:
        return "high"
    if score >= 31:
        return "medium"
    return "low"


def _reason(code: str, message: str, action: str) -> tuple[dict, dict]:
    return (
        {"code": code, "message": message},
        {"code": code, "label": action},
    )


def calculate_appointment_risk(
    appt: Appointment,
    customer: Customer,
    conflict_types: set[str] | None = None,
    now: datetime | None = None,
) -> dict:
    now = now or datetime.now(UTC)
    conflicts = conflict_types or set()
    score = 0
    reasons: list[dict] = []
    actions: list[dict] = []

    def add(points: int, code: str, message: str, action: str) -> None:
        nonlocal score
        score += points
        reason, recommended = _reason(code, message, action)
        reasons.append(reason)
        actions.append(recommended)

    starts_in = appt.scheduled_at - now
    if appt.status in {"scheduled", "rescheduled"} and timedelta(0) <= starts_in <= timedelta(
        hours=2
    ):
        add(
            25,
            "starts_soon_unconfirmed",
            "Empieza en menos de 2 horas y no está confirmada.",
            "Enviar confirmación por WhatsApp",
        )
    if appt.last_customer_reply_at and now - appt.last_customer_reply_at > timedelta(hours=12):
        add(
            15,
            "no_recent_reply",
            "Cliente sin respuesta reciente por más de 12 horas.",
            "Enviar recordatorio corto",
        )
    if not customer.phone_e164:
        add(30, "missing_phone", "Cliente sin teléfono WhatsApp.", "Capturar teléfono")
    if not appt.advisor_name:
        add(20, "missing_advisor", "Cita sin asesor asignado.", "Asignar asesor")
    if appt.appointment_type == "test_drive" and not appt.vehicle_label:
        add(20, "missing_vehicle", "Prueba de manejo sin unidad asignada.", "Asignar unidad")
    if not appt.documents_complete:
        add(15, "documents_incomplete", "Documentos incompletos.", "Solicitar documentos")
    if appt.down_payment_amount and not appt.down_payment_confirmed:
        add(15, "down_payment_unconfirmed", "Enganche no confirmado.", "Confirmar enganche")
    attrs = customer.attrs or {}
    if int(attrs.get("previous_no_shows") or 0) > 0:
        add(
            20, "previous_no_show", "Cliente con no-show previo.", "Confirmar asistencia con humano"
        )
    if "advisor_overlap" in conflicts:
        add(
            25,
            "advisor_overlap",
            "Traslape con otra cita del asesor.",
            "Reprogramar o cambiar asesor",
        )
    if "vehicle_overlap" in conflicts:
        add(25, "vehicle_overlap", "Traslape de unidad.", "Cambiar unidad")
    if appt.ai_confidence is not None and appt.ai_confidence < 0.7:
        add(
            10,
            "low_ai_confidence",
            "Cita creada por IA con baja confianza.",
            "Revisar datos extraídos",
        )
    local_start = _as_tz(appt.scheduled_at, appt.timezone or DEFAULT_TIMEZONE).time()
    local_end = _as_tz(_end_for(appt), appt.timezone or DEFAULT_TIMEZONE).time()
    if local_start < WORKDAY_START or local_end > WORKDAY_END:
        add(
            15,
            "outside_business_hours",
            "Cita fuera de horario laboral.",
            "Reprogramar dentro de horario",
        )
    last_message = str((appt.ops_config or {}).get("last_customer_message") or "").lower()
    if any(word in last_message for word in ("duda", "no puedo", "caro", "cancel", "molest")):
        add(
            10,
            "friction_message",
            "Último mensaje contiene duda o fricción.",
            "Enviar respuesta de aclaración",
        )

    score = max(0, min(100, score))
    return {
        "score": score,
        "level": _risk_level(score),
        "reasons": reasons,
        "recommended_actions": actions[:4],
    }


def _build_conflict_map(
    rows: list[tuple[Appointment, Customer]],
) -> tuple[dict[UUID, set[str]], list[dict]]:
    conflict_map: dict[UUID, set[str]] = defaultdict(set)
    conflicts: list[dict] = []
    active = [(a, c) for a, c in rows if a.status in ACTIVE_STATUSES]

    for appt, customer in active:
        local = _as_tz(appt.scheduled_at, appt.timezone or DEFAULT_TIMEZONE)
        local_end = _as_tz(_end_for(appt), appt.timezone or DEFAULT_TIMEZONE)
        if not appt.advisor_name:
            conflict_map[appt.id].add("missing_advisor")
            conflicts.append(
                {
                    "appointment_id": str(appt.id),
                    "type": "missing_advisor",
                    "severity": "high",
                    "message": "Cita sin asesor asignado",
                }
            )
        if appt.appointment_type == "test_drive" and not appt.vehicle_label:
            conflict_map[appt.id].add("missing_vehicle")
            conflicts.append(
                {
                    "appointment_id": str(appt.id),
                    "type": "missing_vehicle",
                    "severity": "high",
                    "message": "Prueba de manejo sin unidad",
                }
            )
        if not customer.phone_e164:
            conflict_map[appt.id].add("missing_phone")
            conflicts.append(
                {
                    "appointment_id": str(appt.id),
                    "type": "missing_phone",
                    "severity": "critical",
                    "message": "Cliente sin WhatsApp",
                }
            )
        if local.time() < WORKDAY_START or local_end.time() > WORKDAY_END:
            conflict_map[appt.id].add("outside_business_hours")
            conflicts.append(
                {
                    "appointment_id": str(appt.id),
                    "type": "outside_business_hours",
                    "severity": "medium",
                    "message": "Fuera de horario laboral",
                }
            )

    for i, (a, ac) in enumerate(active):
        a_end = _end_for(a)
        for b, bc in active[i + 1 :]:
            b_end = _end_for(b)
            overlaps = a.scheduled_at < b_end and b.scheduled_at < a_end
            if not overlaps:
                continue
            if a.advisor_id and a.advisor_id == b.advisor_id:
                conflict_map[a.id].add("advisor_overlap")
                conflict_map[b.id].add("advisor_overlap")
                conflicts.append(
                    {
                        "appointment_id": str(a.id),
                        "related_appointment_id": str(b.id),
                        "type": "advisor_overlap",
                        "severity": "critical",
                        "message": f"Traslape de asesor: {a.advisor_name}",
                    }
                )
            if a.vehicle_id and a.vehicle_id == b.vehicle_id:
                conflict_map[a.id].add("vehicle_overlap")
                conflict_map[b.id].add("vehicle_overlap")
                conflicts.append(
                    {
                        "appointment_id": str(a.id),
                        "related_appointment_id": str(b.id),
                        "type": "vehicle_overlap",
                        "severity": "critical",
                        "message": f"Traslape de unidad: {a.vehicle_label}",
                    }
                )
            if a.customer_id == b.customer_id and a.scheduled_at.date() == b.scheduled_at.date():
                conflict_map[a.id].add("duplicate_customer_day")
                conflict_map[b.id].add("duplicate_customer_day")
                conflicts.append(
                    {
                        "appointment_id": str(a.id),
                        "related_appointment_id": str(b.id),
                        "type": "duplicate_customer_day",
                        "severity": "medium",
                        "message": f"Citas duplicadas para {ac.name or bc.name}",
                    }
                )

    return conflict_map, conflicts


def _item(
    appt: Appointment, customer: Customer, conflict_types: set[str] | None = None
) -> AppointmentItem:
    risk = calculate_appointment_risk(appt, customer, conflict_types)
    return AppointmentItem(
        id=appt.id,
        customer_id=appt.customer_id,
        customer_name=customer.name,
        customer_phone=customer.phone_e164,
        conversation_id=appt.conversation_id,
        scheduled_at=appt.scheduled_at,
        ends_at=appt.ends_at or _end_for(appt),
        appointment_type=appt.appointment_type,
        service=appt.service,
        status=appt.status,
        notes=appt.notes,
        timezone=appt.timezone,
        source=appt.source,
        advisor_id=appt.advisor_id,
        advisor_name=appt.advisor_name,
        vehicle_id=appt.vehicle_id,
        vehicle_label=appt.vehicle_label,
        ai_confidence=appt.ai_confidence,
        risk_score=risk["score"],
        risk_level=risk["level"],
        risk_reasons=risk["reasons"],
        recommended_actions=risk["recommended_actions"],
        credit_plan=appt.credit_plan,
        down_payment_amount=appt.down_payment_amount,
        down_payment_confirmed=appt.down_payment_confirmed,
        documents_complete=appt.documents_complete,
        last_customer_reply_at=appt.last_customer_reply_at,
        confirmed_at=appt.confirmed_at,
        arrived_at=appt.arrived_at,
        completed_at=appt.completed_at,
        cancelled_at=appt.cancelled_at,
        no_show_at=appt.no_show_at,
        reminder_status=appt.reminder_status,
        reminder_last_sent_at=appt.reminder_last_sent_at,
        action_log=appt.action_log or [],
        created_by_type=appt.created_by_type,
        created_at=appt.created_at,
        updated_at=appt.updated_at,
        conflict_count=len(conflict_types or set()),
    )


async def _assert_customer(session: AsyncSession, *, tenant_id: UUID, customer_id: UUID) -> None:
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


async def _get_row(
    session: AsyncSession, *, tenant_id: UUID, appointment_id: UUID
) -> tuple[Appointment, Customer]:
    row = (
        await session.execute(
            select(Appointment, Customer)
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
    return row[0], row[1]


async def _find_conflicts(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    customer_id: UUID,
    scheduled_at: datetime,
    exclude_id: UUID | None = None,
) -> list[AppointmentConflictItem]:
    lower = scheduled_at - APPOINTMENT_CONFLICT_WINDOW
    upper = scheduled_at + APPOINTMENT_CONFLICT_WINDOW
    stmt = select(
        Appointment.id, Appointment.scheduled_at, Appointment.service, Appointment.status
    ).where(
        Appointment.tenant_id == tenant_id,
        Appointment.customer_id == customer_id,
        Appointment.deleted_at.is_(None),
        Appointment.status.in_(ACTIVE_STATUSES),
        Appointment.scheduled_at >= lower,
        Appointment.scheduled_at <= upper,
    )
    if exclude_id is not None:
        stmt = stmt.where(Appointment.id != exclude_id)
    return [
        AppointmentConflictItem(
            id=row.id, scheduled_at=row.scheduled_at, service=row.service, status=row.status
        )
        for row in (await session.execute(stmt)).all()
    ]


async def _find_exact_appointment_id(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    customer_id: UUID,
    scheduled_at: datetime,
    service: str,
) -> UUID | None:
    return (
        await session.execute(
            select(Appointment.id)
            .where(
                Appointment.tenant_id == tenant_id,
                Appointment.customer_id == customer_id,
                Appointment.scheduled_at == scheduled_at,
                Appointment.service == service,
                Appointment.deleted_at.is_(None),
            )
            .limit(1)
        )
    ).scalar_one_or_none()


def _append_log(
    row: Appointment, action: str, actor: AuthUser | None, payload: dict[str, Any] | None = None
) -> None:
    entry = {
        "id": f"log_{datetime.now(UTC).timestamp():.0f}",
        "action": action,
        "actor": actor.email if actor else "Sistema",
        "payload": payload or {},
        "created_at": datetime.now(UTC).isoformat(),
    }
    row.action_log = [entry, *(row.action_log or [])][:30]


async def _recalculate_row(session: AsyncSession, row: Appointment, customer: Customer) -> None:
    start = row.scheduled_at - timedelta(hours=4)
    end = _end_for(row) + timedelta(hours=4)
    rows = (
        await session.execute(
            select(Appointment, Customer)
            .join(Customer, Customer.id == Appointment.customer_id)
            .where(
                Appointment.tenant_id == row.tenant_id,
                Appointment.deleted_at.is_(None),
                Appointment.scheduled_at >= start,
                Appointment.scheduled_at < end,
            )
        )
    ).all()
    conflict_map, _conflicts = _build_conflict_map([(appt, cust) for appt, cust in rows])
    risk = calculate_appointment_risk(row, customer, conflict_map.get(row.id, set()))
    row.risk_score = risk["score"]
    row.risk_level = risk["level"]
    row.risk_reasons = risk["reasons"]
    row.recommended_actions = risk["recommended_actions"]


async def _query_rows(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    customer_id: UUID | None = None,
    appointment_status: str | None = None,
    limit: int = 300,
) -> list[tuple[Appointment, Customer]]:
    stmt = (
        select(Appointment, Customer)
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
        stmt = stmt.where(Appointment.status == appointment_status)
    return [(row[0], row[1]) for row in (await session.execute(stmt)).all()]


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
    if appointment_status is not None and appointment_status not in APPOINTMENT_STATUSES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid appointment status")
    rows = await _query_rows(
        session,
        tenant_id=tenant_id,
        date_from=date_from,
        date_to=date_to,
        customer_id=customer_id,
        appointment_status=appointment_status,
        limit=limit,
    )
    conflict_map, _conflicts = _build_conflict_map(rows)
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
    return AppointmentListResponse(
        items=[_item(appt, customer, conflict_map.get(appt.id, set())) for appt, customer in rows],
        total=total,
    )


@router.get("/kpis")
async def appointment_kpis(
    user: AuthUser = Depends(current_user),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    now = datetime.now(UTC)
    local_now = datetime.now(ZoneInfo(DEFAULT_TIMEZONE))
    day_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)
    day_end = (
        local_now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    ).astimezone(UTC)
    week_start = (
        (local_now - timedelta(days=local_now.weekday()))
        .replace(hour=0, minute=0, second=0, microsecond=0)
        .astimezone(UTC)
    )
    week_end = week_start + timedelta(days=7)
    rows = await _query_rows(
        session, tenant_id=tenant_id, date_from=week_start, date_to=week_end, limit=300
    )
    conflict_map, conflicts = _build_conflict_map(rows)
    items = [_item(appt, customer, conflict_map.get(appt.id, set())) for appt, customer in rows]
    today = [item for item in items if day_start <= item.scheduled_at < day_end]
    estimated = sum(
        220000
        for item in items
        if item.status in ACTIVE_STATUSES
        and item.appointment_type in {"test_drive", "quote", "financing"}
    )
    return {
        "today": len(today),
        "confirmed": sum(1 for item in items if item.status == "confirmed"),
        "high_risk": sum(1 for item in items if item.risk_level in {"high", "critical"}),
        "probable_no_show": sum(
            1 for item in items if item.risk_score >= 61 and item.status in ACTIVE_STATUSES
        ),
        "missing_advisor": sum(
            1 for item in items if not item.advisor_name and item.status in ACTIVE_STATUSES
        ),
        "incomplete_docs": sum(
            1 for item in items if not item.documents_complete and item.status in ACTIVE_STATUSES
        ),
        "estimated_opportunity_mxn": estimated,
        "this_week": len(items),
        "conflicts": len(conflicts),
        "completed": sum(1 for item in items if item.status == "completed"),
        "live_at": now.isoformat(),
    }


@router.get("/conflicts")
async def appointment_conflicts(
    user: AuthUser = Depends(current_user),
    tenant_id: UUID = Depends(current_tenant_id),
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    session: AsyncSession = Depends(get_db_session),
) -> list[dict]:
    rows = await _query_rows(
        session, tenant_id=tenant_id, date_from=date_from, date_to=date_to, limit=300
    )
    _map, conflicts = _build_conflict_map(rows)
    return conflicts


@router.get("/priority-feed")
async def priority_feed(
    user: AuthUser = Depends(current_user),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> list[dict]:
    now = datetime.now(UTC)
    rows = await _query_rows(
        session,
        tenant_id=tenant_id,
        date_from=now - timedelta(days=2),
        date_to=now + timedelta(days=14),
        limit=300,
    )
    conflict_map, _conflicts = _build_conflict_map(rows)
    priorities: list[dict] = []
    for appt, customer in rows:
        item = _item(appt, customer, conflict_map.get(appt.id, set()))
        starts_in = item.scheduled_at - now
        if item.risk_level in {"critical", "high"}:
            priorities.append(
                {
                    "id": f"risk_{item.id}",
                    "appointment_id": str(item.id),
                    "severity": item.risk_level,
                    "reason": item.risk_reasons[0]["message"]
                    if item.risk_reasons
                    else "Riesgo alto",
                    "customer": item.customer_name or item.customer_phone,
                    "time": item.scheduled_at.isoformat(),
                    "vehicle": item.vehicle_label,
                    "recommended_action": item.recommended_actions[0]["label"]
                    if item.recommended_actions
                    else "Revisar cita",
                    "actions": ["send-reminder", "reschedule"],
                    "sort": 0 if item.risk_level == "critical" else 1,
                }
            )
        elif timedelta(0) <= starts_in <= timedelta(hours=2) and item.status == "scheduled":
            priorities.append(
                {
                    "id": f"soon_{item.id}",
                    "appointment_id": str(item.id),
                    "severity": "medium",
                    "reason": f"Cita en {int(starts_in.total_seconds() // 60)} min sin confirmar",
                    "customer": item.customer_name or item.customer_phone,
                    "time": item.scheduled_at.isoformat(),
                    "vehicle": item.vehicle_label,
                    "recommended_action": "Enviar WhatsApp",
                    "actions": ["send-reminder", "confirm"],
                    "sort": 2,
                }
            )
        elif item.status == "completed" and not any(
            log.get("action") == "follow_up_created" for log in item.action_log
        ):
            priorities.append(
                {
                    "id": f"follow_{item.id}",
                    "appointment_id": str(item.id),
                    "severity": "low",
                    "reason": "Cita completada sin seguimiento",
                    "customer": item.customer_name or item.customer_phone,
                    "time": item.scheduled_at.isoformat(),
                    "vehicle": item.vehicle_label,
                    "recommended_action": "Crear seguimiento",
                    "actions": ["create-follow-up"],
                    "sort": 5,
                }
            )
        elif item.status == "no_show":
            priorities.append(
                {
                    "id": f"noshow_{item.id}",
                    "appointment_id": str(item.id),
                    "severity": "high",
                    "reason": "No-show pendiente de reactivación",
                    "customer": item.customer_name or item.customer_phone,
                    "time": item.scheduled_at.isoformat(),
                    "vehicle": item.vehicle_label,
                    "recommended_action": "Reactivar por WhatsApp",
                    "actions": ["send-reminder", "reschedule"],
                    "sort": 6,
                }
            )
    return sorted(priorities, key=lambda row: (row["sort"], row["time"]))[:12]


@router.get("/funnel")
async def appointment_funnel(
    user: AuthUser = Depends(current_user),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> list[dict]:
    local_now = datetime.now(ZoneInfo(DEFAULT_TIMEZONE))
    start = (
        (local_now - timedelta(days=local_now.weekday()))
        .replace(hour=0, minute=0, second=0, microsecond=0)
        .astimezone(UTC)
    )
    rows = await _query_rows(
        session, tenant_id=tenant_id, date_from=start, date_to=start + timedelta(days=7), limit=300
    )
    items = [_item(appt, customer) for appt, customer in rows]
    total = max(len(items), 1)
    stages = [
        ("Agendadas", len(items), 4),
        (
            "Confirmadas",
            sum(1 for item in items if item.status in {"confirmed", "arrived", "completed"}),
            3,
        ),
        ("Llegaron", sum(1 for item in items if item.status in {"arrived", "completed"}), 6),
        (
            "Cotizadas",
            sum(
                1
                for item in items
                if item.appointment_type in {"quote", "financing"} or item.status == "completed"
            ),
            2,
        ),
        ("Enganche listo", sum(1 for item in items if item.down_payment_confirmed), -1),
        ("Vendidas", max(1, sum(1 for item in items if item.status == "completed") // 3), 2),
        ("No-show", sum(1 for item in items if item.status == "no_show"), -3),
    ]
    return [
        {
            "stage": label,
            "count": count,
            "conversion": round(count / total * 100),
            "trend": trend,
        }
        for label, count, trend in stages
    ]


@router.get("/supervisor-recommendations")
async def supervisor_recommendations(
    user: AuthUser = Depends(current_user),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    priorities = await priority_feed(user, tenant_id, session)
    return {
        "health": "Óptima" if len(priorities) < 6 else "Atención requerida",
        "recommendations": [
            {
                "id": "rec_confirm",
                "severity": "high",
                "title": "Confirmar citas próximas",
                "detail": "Prioriza citas en las siguientes 2 horas sin confirmación.",
                "action": "Enviar recordatorios",
            },
            {
                "id": "rec_advisor",
                "severity": "medium",
                "title": "Balancear carga de asesores",
                "detail": "María y Diego tienen ventanas disponibles antes de las 17:00.",
                "action": "Reasignar citas",
            },
            {
                "id": "rec_docs",
                "severity": "medium",
                "title": "Solicitar documentos faltantes",
                "detail": "Hay clientes con INE o comprobante pendiente.",
                "action": "Solicitar documentos",
            },
        ],
        "risks_today": len([p for p in priorities if p["severity"] in {"critical", "high"}]),
        "open_slots": [
            {"advisor": "María González", "time": "15:30"},
            {"advisor": "Diego Morales", "time": "17:00"},
            {"advisor": "Sofía Nava", "time": "18:15"},
        ],
    }


@router.get("/advisors")
async def advisors(
    provider: AdvisorProvider = Depends(get_advisor_provider),
) -> list[dict]:
    return await provider.list_advisors()


@router.get("/vehicles")
async def vehicles(
    provider: VehicleProvider = Depends(get_vehicle_provider),
) -> list[dict]:
    return await provider.list_vehicles()


class AdvisorCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=160)
    phone: str | None = Field(default=None, max_length=40)
    max_per_day: int = Field(default=6, ge=0, le=100)
    close_rate: float = Field(default=0.0, ge=0.0, le=1.0)


class VehicleCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=80)
    label: str = Field(min_length=1, max_length=160)
    status: str = Field(default="available", max_length=30)
    available_for_test_drive: bool = True


@router.post("/advisors", status_code=status.HTTP_201_CREATED)
async def create_advisor(
    body: AdvisorCreate,
    user: AuthUser = Depends(require_tenant_admin),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    advisor = Advisor(
        tenant_id=tenant_id,
        id=body.id,
        name=body.name,
        phone=body.phone,
        max_per_day=body.max_per_day,
        close_rate=body.close_rate,
    )
    session.add(advisor)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"advisor '{body.id}' already exists for this tenant",
        ) from exc
    await emit_admin_event(
        session,
        tenant_id=tenant_id,
        actor_user_id=user.user_id,
        action="advisor.create",
        payload={"id": body.id, "name": body.name},
    )
    return {
        "id": advisor.id,
        "name": advisor.name,
        "phone": advisor.phone,
        "max_per_day": advisor.max_per_day,
        "close_rate": advisor.close_rate,
    }


@router.post("/vehicles", status_code=status.HTTP_201_CREATED)
async def create_vehicle(
    body: VehicleCreate,
    user: AuthUser = Depends(require_tenant_admin),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    vehicle = Vehicle(
        tenant_id=tenant_id,
        id=body.id,
        label=body.label,
        status=body.status,
        available_for_test_drive=body.available_for_test_drive,
    )
    session.add(vehicle)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"vehicle '{body.id}' already exists for this tenant",
        ) from exc
    await emit_admin_event(
        session,
        tenant_id=tenant_id,
        actor_user_id=user.user_id,
        action="vehicle.create",
        payload={"id": body.id, "label": body.label},
    )
    return {
        "id": vehicle.id,
        "label": vehicle.label,
        "status": vehicle.status,
        "available_for_test_drive": vehicle.available_for_test_drive,
    }


@router.post("/parse-natural-language", response_model=ParseNaturalResponse)
async def parse_natural_language(body: ParseNaturalBody) -> ParseNaturalResponse:
    return _parse_natural_appointment(body.text, body.timezone, body.now)


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
    ends_utc = (
        body.ends_at.astimezone(UTC)
        if body.ends_at
        else scheduled_utc + _duration_for(body.appointment_type)
    )
    service = body.service.strip()
    conflicts = await _find_conflicts(
        session,
        tenant_id=tenant_id,
        customer_id=body.customer_id,
        scheduled_at=scheduled_utc,
    )
    existing_id = await _find_exact_appointment_id(
        session,
        tenant_id=tenant_id,
        customer_id=body.customer_id,
        scheduled_at=scheduled_utc,
        service=service,
    )
    if existing_id is not None:
        appt, customer = await _get_row(session, tenant_id=tenant_id, appointment_id=existing_id)
        return AppointmentCreateResponse(appointment=_item(appt, customer), conflicts=conflicts)
    appt = Appointment(
        tenant_id=tenant_id,
        customer_id=body.customer_id,
        conversation_id=body.conversation_id,
        scheduled_at=scheduled_utc,
        ends_at=ends_utc,
        appointment_type=body.appointment_type,
        service=service,
        notes=body.notes,
        timezone=body.timezone,
        source=body.source,
        created_by_id=user.user_id,
        created_by_type="ai" if body.source == "ai_parser" else "user",
        advisor_id=body.advisor_id,
        advisor_name=body.advisor_name,
        vehicle_id=body.vehicle_id,
        vehicle_label=body.vehicle_label,
        ai_confidence=body.ai_confidence,
        credit_plan=body.credit_plan,
        down_payment_amount=body.down_payment_amount,
        down_payment_confirmed=body.down_payment_confirmed,
        documents_complete=body.documents_complete,
        last_customer_reply_at=body.last_customer_reply_at,
    )
    try:
        async with session.begin_nested():
            session.add(appt)
            await session.flush()
    except IntegrityError:
        existing_id = await _find_exact_appointment_id(
            session,
            tenant_id=tenant_id,
            customer_id=body.customer_id,
            scheduled_at=scheduled_utc,
            service=service,
        )
        if existing_id is None:
            raise
        appt, customer = await _get_row(session, tenant_id=tenant_id, appointment_id=existing_id)
        return AppointmentCreateResponse(appointment=_item(appt, customer), conflicts=conflicts)
    appt, customer = await _get_row(session, tenant_id=tenant_id, appointment_id=appt.id)
    await _recalculate_row(session, appt, customer)
    _append_log(appt, "created", user, {"source": body.source})
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
    appt, customer = await _get_row(session, tenant_id=tenant_id, appointment_id=appt.id)
    return AppointmentCreateResponse(appointment=_item(appt, customer), conflicts=conflicts)


@router.get("/{appointment_id}", response_model=AppointmentItem)
async def get_appointment(
    appointment_id: UUID,
    user: AuthUser = Depends(current_user),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> AppointmentItem:
    appt, customer = await _get_row(session, tenant_id=tenant_id, appointment_id=appointment_id)
    return _item(appt, customer)


@router.patch("/{appointment_id}", response_model=AppointmentItem)
async def patch_appointment(
    appointment_id: UUID,
    body: AppointmentPatch,
    user: AuthUser = Depends(current_user),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> AppointmentItem:
    appt, customer = await _get_row(session, tenant_id=tenant_id, appointment_id=appointment_id)
    values = body.model_dump(exclude_unset=True)
    if not values:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "no fields to update")
    if values.get("scheduled_at") is not None:
        values["scheduled_at"] = values["scheduled_at"].astimezone(UTC)
    if values.get("ends_at") is not None:
        values["ends_at"] = values["ends_at"].astimezone(UTC)
    if values.get("last_customer_reply_at") is not None:
        values["last_customer_reply_at"] = values["last_customer_reply_at"].astimezone(UTC)
    if values.get("service") is not None:
        values["service"] = values["service"].strip()
    status_value = values.get("status")
    if status_value in STATUS_TIMESTAMPS:
        values[STATUS_TIMESTAMPS[status_value]] = datetime.now(UTC)
    values["updated_at"] = datetime.now(UTC)
    await session.execute(
        update(Appointment).where(Appointment.id == appointment_id).values(**values)
    )
    await session.flush()
    appt, customer = await _get_row(session, tenant_id=tenant_id, appointment_id=appointment_id)
    _append_log(appt, "patched", user, {"fields": sorted(k for k in values if k != "updated_at")})
    await _recalculate_row(session, appt, customer)
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
    appt, customer = await _get_row(session, tenant_id=tenant_id, appointment_id=appointment_id)
    return _item(appt, customer)


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


async def _action_update(
    appointment_id: UUID,
    user: AuthUser,
    tenant_id: UUID,
    session: AsyncSession,
    action: str,
    values: dict[str, Any] | None = None,
    payload: dict[str, Any] | None = None,
) -> AppointmentItem:
    appt, customer = await _get_row(session, tenant_id=tenant_id, appointment_id=appointment_id)
    for key, value in (values or {}).items():
        setattr(appt, key, value)
    appt.updated_at = datetime.now(UTC)
    _append_log(appt, action, user, payload)
    await _recalculate_row(session, appt, customer)
    await emit_admin_event(
        session,
        tenant_id=tenant_id,
        actor_user_id=user.user_id,
        action=f"appointment.{action}",
        payload={"appointment_id": str(appointment_id), **(payload or {})},
    )
    await session.commit()
    await session.refresh(appt)
    return _item(appt, customer)


@router.post("/{appointment_id}/confirm", response_model=AppointmentItem)
async def confirm_appointment(
    appointment_id: UUID,
    user: AuthUser = Depends(current_user),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> AppointmentItem:
    return await _action_update(
        appointment_id,
        user,
        tenant_id,
        session,
        "confirmed",
        {"status": "confirmed", "confirmed_at": datetime.now(UTC)},
    )


@router.post("/{appointment_id}/send-reminder", response_model=AppointmentItem)
async def send_reminder(
    appointment_id: UUID,
    user: AuthUser = Depends(current_user),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
    messaging: MessageActionProvider = Depends(get_messaging_provider),
) -> AppointmentItem:
    result = await messaging.send_reminder(appointment_id)
    return await _action_update(
        appointment_id,
        user,
        tenant_id,
        session,
        "reminder_sent",
        {"reminder_status": "sent", "reminder_last_sent_at": datetime.now(UTC)},
        result,
    )


@router.post("/{appointment_id}/send-location", response_model=AppointmentItem)
async def send_location(
    appointment_id: UUID,
    user: AuthUser = Depends(current_user),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
    messaging: MessageActionProvider = Depends(get_messaging_provider),
) -> AppointmentItem:
    result = await messaging.send_location(appointment_id)
    return await _action_update(
        appointment_id, user, tenant_id, session, "location_sent", payload=result
    )


@router.post("/{appointment_id}/mark-arrived", response_model=AppointmentItem)
async def mark_arrived(
    appointment_id: UUID,
    user: AuthUser = Depends(current_user),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> AppointmentItem:
    return await _action_update(
        appointment_id,
        user,
        tenant_id,
        session,
        "arrived",
        {"status": "arrived", "arrived_at": datetime.now(UTC)},
    )


@router.post("/{appointment_id}/mark-completed", response_model=AppointmentItem)
async def mark_completed(
    appointment_id: UUID,
    user: AuthUser = Depends(current_user),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> AppointmentItem:
    return await _action_update(
        appointment_id,
        user,
        tenant_id,
        session,
        "completed",
        {"status": "completed", "completed_at": datetime.now(UTC)},
    )


@router.post("/{appointment_id}/mark-no-show", response_model=AppointmentItem)
async def mark_no_show(
    appointment_id: UUID,
    user: AuthUser = Depends(current_user),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> AppointmentItem:
    return await _action_update(
        appointment_id,
        user,
        tenant_id,
        session,
        "no_show",
        {"status": "no_show", "no_show_at": datetime.now(UTC)},
    )


@router.post("/{appointment_id}/reschedule", response_model=AppointmentItem)
async def reschedule_appointment(
    appointment_id: UUID,
    body: RescheduleBody,
    user: AuthUser = Depends(current_user),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> AppointmentItem:
    scheduled = body.scheduled_at.astimezone(UTC)
    ends = body.ends_at.astimezone(UTC) if body.ends_at else scheduled + timedelta(minutes=45)
    return await _action_update(
        appointment_id,
        user,
        tenant_id,
        session,
        "rescheduled",
        {"status": "rescheduled", "scheduled_at": scheduled, "ends_at": ends},
    )


@router.post("/{appointment_id}/change-advisor", response_model=AppointmentItem)
async def change_advisor(
    appointment_id: UUID,
    body: ChangeAdvisorBody,
    user: AuthUser = Depends(current_user),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> AppointmentItem:
    return await _action_update(
        appointment_id,
        user,
        tenant_id,
        session,
        "advisor_changed",
        {"advisor_id": body.advisor_id, "advisor_name": body.advisor_name},
    )


@router.post("/{appointment_id}/change-vehicle", response_model=AppointmentItem)
async def change_vehicle(
    appointment_id: UUID,
    body: ChangeVehicleBody,
    user: AuthUser = Depends(current_user),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> AppointmentItem:
    return await _action_update(
        appointment_id,
        user,
        tenant_id,
        session,
        "vehicle_changed",
        {"vehicle_id": body.vehicle_id, "vehicle_label": body.vehicle_label},
    )


@router.post("/{appointment_id}/request-documents", response_model=AppointmentItem)
async def request_documents(
    appointment_id: UUID,
    user: AuthUser = Depends(current_user),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
    messaging: MessageActionProvider = Depends(get_messaging_provider),
) -> AppointmentItem:
    result = await messaging.request_documents(appointment_id)
    return await _action_update(
        appointment_id, user, tenant_id, session, "documents_requested", payload=result
    )


@router.post("/{appointment_id}/create-follow-up", response_model=AppointmentItem)
async def create_follow_up(
    appointment_id: UUID,
    body: FollowUpBody | None = None,
    user: AuthUser = Depends(current_user),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> AppointmentItem:
    payload = {"title": (body.title if body else "Seguimiento posterior a cita")}
    if body and body.due_at:
        payload["due_at"] = body.due_at.isoformat()
    return await _action_update(
        appointment_id, user, tenant_id, session, "follow_up_created", payload=payload
    )


def _parse_natural_appointment(
    text: str, timezone: str, now: datetime | None = None
) -> ParseNaturalResponse:
    zone = ZoneInfo(timezone)
    base = (now or datetime.now(zone)).astimezone(zone)
    lower = text.lower()
    date_value = base
    if "pasado mañana" in lower:
        date_value = base + timedelta(days=2)
    elif "mañana" in lower:
        date_value = base + timedelta(days=1)
    elif "hoy" in lower:
        date_value = base
    else:
        days = {
            "lunes": 0,
            "martes": 1,
            "miércoles": 2,
            "miercoles": 2,
            "jueves": 3,
            "viernes": 4,
            "sábado": 5,
            "sabado": 5,
            "domingo": 6,
        }
        for name, weekday in days.items():
            if name in lower:
                diff = weekday - base.weekday()
                if diff <= 0:
                    diff += 7
                date_value = base + timedelta(days=diff)
                break

    hour = 9
    minute = 0
    time_match = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm|a\.m\.|p\.m\.|hrs?)?\b", lower)
    if time_match:
        hour = int(time_match.group(1))
        minute = int(time_match.group(2) or 0)
        meridian = (time_match.group(3) or "").replace(".", "")
        if meridian == "pm" and hour < 12:
            hour += 12
        elif meridian == "am" and hour == 12:
            hour = 0
        elif not meridian and 1 <= hour <= 7:
            hour += 12

    appt_type = "follow_up"
    for key, terms in {
        "test_drive": ["prueba de manejo", "manejo"],
        "quote": ["cotización", "cotizacion", "cotizar"],
        "documents": ["documentos", "papeles"],
        "delivery": ["entrega"],
        "financing": ["financiamiento", "crédito", "credito"],
        "call": ["llamada", "llamar"],
        "follow_up": ["seguimiento"],
    }.items():
        if any(term in lower for term in terms):
            appt_type = key
            break

    from atendia._demo.fixtures import DEMO_ADVISORS, DEMO_VEHICLES

    vehicle_label = None
    for vehicle in DEMO_VEHICLES:
        if vehicle["label"].lower() in lower:
            vehicle_label = vehicle["label"]
            break

    advisor_name = None
    for advisor in DEMO_ADVISORS:
        first = advisor["name"].split()[0].lower()
        if f"asesor {first}" in lower or f"con {first}" in lower:
            advisor_name = advisor["name"]
            break

    customer_name = None
    name_match = re.search(
        r"(?:para|con|a)\s+([A-ZÁÉÍÓÚÑ][a-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+)?)", text
    )
    if name_match:
        customer_name = name_match.group(1).strip()
        stop_words = [
            " el ",
            " la ",
            " mañana",
            " hoy",
            " viernes",
            " jueves",
            " lunes",
            " martes",
            " miércoles",
            " miercoles",
            " sábado",
            " sabado",
            " domingo",
            " para ",
        ]
        for token in stop_words:
            pos = customer_name.lower().find(token.strip())
            if pos > 0:
                customer_name = customer_name[:pos].strip()

    phone_match = re.search(r"(\+?52)?\s?(\d{10})", text)
    phone = phone_match.group(0).replace(" ", "") if phone_match else None
    money_match = re.search(
        r"\$?\s?(\d{1,3}(?:,\d{3})+|\d+)\s*(mil)?(?:\s+de\s+enganche|.*enganche)?", lower
    )
    down_payment = None
    if "enganche" in lower and money_match:
        amount = int(money_match.group(1).replace(",", ""))
        down_payment = amount * 1000 if money_match.group(2) == "mil" and amount < 1000 else amount

    scheduled = date_value.replace(hour=hour, minute=minute, second=0, microsecond=0)
    ends = scheduled + _duration_for(appt_type)
    missing = []
    if not customer_name:
        missing.append("cliente")
    if appt_type == "test_drive" and not vehicle_label:
        missing.append("unidad")
    confidence = 0.92 - (0.12 * len(missing))
    service = _type_label(appt_type)
    return ParseNaturalResponse(
        understood=True,
        confidence=max(0.55, confidence),
        date=scheduled.date().isoformat(),
        time=scheduled.strftime("%H:%M"),
        appointment_type=appt_type,
        service=service,
        customer_name=customer_name,
        customer_phone=phone,
        vehicle_label=vehicle_label,
        advisor_name=advisor_name,
        down_payment_amount=down_payment,
        scheduled_at=scheduled.astimezone(UTC),
        ends_at=ends.astimezone(UTC),
        summary=f"{service} para {customer_name or 'cliente no especificado'} el {scheduled.strftime('%d/%m %H:%M')}",
        missing_fields=missing,
    )
