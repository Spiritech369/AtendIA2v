from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from redis.asyncio import Redis
from sqlalchemy import and_, exists, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.api._auth_helpers import AuthUser
from atendia.api._deps import current_tenant_id, current_user
from atendia.config import get_settings
from atendia.contracts.event import EventType
from atendia.db.models.appointment import Appointment
from atendia.db.models.conversation import Conversation, ConversationStateRow
from atendia.db.models.customer import Customer
from atendia.db.models.lifecycle import HumanHandoff
from atendia.db.models.message import MessageRow
from atendia.db.models.tenant import TenantUser
from atendia.db.models.tenant_config import TenantPipeline
from atendia.db.session import get_db_session
from atendia.realtime.publisher import publish_event
from atendia.state_machine.event_emitter import EventEmitter

router = APIRouter()


class PipelineConversationCard(BaseModel):
    id: UUID
    customer_id: UUID
    customer_name: str | None
    customer_phone: str
    last_message_text: str | None
    last_activity_at: datetime
    stage_entered_at: datetime | None = None
    current_stage: str
    assigned_user_id: UUID | None = None
    assigned_user_email: str | None = None
    lead_score: int = 0
    source: str | None = None
    campaign: str | None = None
    product: str | None = None
    credit_type: str | None = None
    financing_plan: str | None = None
    estimated_value_mxn: int | None = None
    document_done: int = 0
    document_total: int = 0
    document_percent: int = 0
    missing_documents: list[str] = []
    appointment_at: datetime | None = None
    appointment_status: str | None = None
    appointment_service: str | None = None
    has_pending_handoff: bool = False
    is_stale: bool
    risk_level: str = "normal"
    risks: list[str] = []
    next_best_action: str | None = None


class StageGroup(BaseModel):
    stage_id: str
    stage_label: str
    total_count: int
    timeout_hours: int | None
    stage_color: str | None = None
    stage_icon: str | None = None
    is_terminal: bool = False
    health_score: int = 100
    total_value_mxn: int = 0
    stale_count: int = 0
    unassigned_count: int = 0
    docs_blocked_count: int = 0
    # ``True`` for the synthetic "orphan" group — conversations whose
    # ``current_stage`` is not in the active pipeline (e.g. the stage was
    # renamed or removed in config). Without this, those conversations
    # silently disappear from the board.
    is_orphan: bool = False
    conversations: list[PipelineConversationCard]


class PipelineBoardResponse(BaseModel):
    stages: list[StageGroup]
    updated_at: datetime
    active_count: int
    pending_handoffs: int
    today_appointments: int
    documents_blocked: int
    credits_in_review: int
    avg_response_seconds: int
    ai_containment_rate: int


class PipelineAlertsResponse(BaseModel):
    items: list[PipelineConversationCard]


class PipelineMoveBody(BaseModel):
    conversation_id: UUID
    to_stage: str


class PipelineMoveResponse(BaseModel):
    id: UUID
    from_stage: str
    current_stage: str
    validated: bool = True


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


def _value(raw: Any) -> Any:
    if isinstance(raw, dict) and "value" in raw:
        return raw.get("value")
    return raw


def _string_value(*values: Any) -> str | None:
    for raw in values:
        value = _value(raw)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _int_value(*values: Any) -> int | None:
    for raw in values:
        value = _value(raw)
        if value in (None, ""):
            continue
        try:
            return int(float(value))
        except (TypeError, ValueError):
            continue
    return None


def _truthy_document(extracted_data: dict, field_name: str) -> bool:
    value = _value(extracted_data.get(field_name))
    if isinstance(value, str):
        return value.strip().lower() in {"true", "si", "sí", "ok", "listo", "aprobado", "1"}
    return bool(value)


def _required_documents(definition: dict, extracted_data: dict) -> list[tuple[str, str]]:
    docs_per_plan = definition.get("docs_per_plan")
    if not isinstance(docs_per_plan, dict):
        return []
    plan = _string_value(extracted_data.get("plan_credito")) or "default"
    required = docs_per_plan.get(plan) or docs_per_plan.get("default") or []
    if not isinstance(required, list):
        return []
    docs: list[tuple[str, str]] = []
    for item in required:
        if isinstance(item, str):
            docs.append((item, item.replace("_", " ")))
        elif isinstance(item, dict):
            field = item.get("field_name") or item.get("field")
            if isinstance(field, str):
                docs.append((field, str(item.get("label") or field.replace("_", " "))))
    return docs


def _document_progress(definition: dict, extracted_data: dict) -> tuple[int, int, int, list[str]]:
    required = _required_documents(definition, extracted_data)
    missing = [label for field, label in required if not _truthy_document(extracted_data, field)]
    total = len(required)
    done = max(total - len(missing), 0)
    percent = round((done / total) * 100) if total else 0
    return done, total, percent, missing


def _terminal_stage(stage_id: str, stage_def: dict | None = None) -> bool:
    if stage_def and stage_def.get("is_terminal") is True:
        return True
    return stage_id in {
        "cierre",
        "cerrado",
        "cerrado_ganado",
        "cerrado_perdido",
        "cierre_ganado",
        "cierre_perdido",
    }


def _opening_stage(stage_id: str) -> bool:
    return stage_id in {"nuevo", "nuevo_lead", "lead_nuevo", "calificacion"}


def _stage_definition(stages: list[dict], stage_id: str) -> dict | None:
    return next((stage for stage in stages if stage.get("id") == stage_id), None)


def _next_best_action(
    *,
    stage_id: str,
    is_stale: bool,
    has_pending_handoff: bool,
    missing_documents: list[str],
    appointment_at: datetime | None,
) -> str:
    if has_pending_handoff:
        return "Atender handoff humano"
    if missing_documents and stage_id in {"documentacion", "documentos", "validacion", "credito"}:
        return f"Solicitar {missing_documents[0]}"
    if appointment_at is None and stage_id in {"propuesta", "negociacion", "cita", "cita_agendada"}:
        return "Agendar prueba de manejo"
    if is_stale:
        return "Enviar seguimiento por WhatsApp"
    if stage_id in {"nuevo", "nuevo_lead", "en_conversacion", "calificacion"}:
        return "Calificar intención y presupuesto"
    return "Revisar siguiente avance"


def _risk_profile(
    *,
    is_stale: bool,
    has_pending_handoff: bool,
    assigned_user_id: UUID | None,
    missing_documents: list[str],
    last_activity_at: datetime,
) -> tuple[str, list[str]]:
    risks: list[str] = []
    now = datetime.now(UTC)
    if has_pending_handoff:
        risks.append("Espera atención humana")
    if assigned_user_id is None:
        risks.append("Lead sin asesor")
    if is_stale:
        risks.append("SLA en riesgo")
    if missing_documents:
        risks.append("Documentos incompletos")
    if last_activity_at < now - timedelta(hours=24):
        risks.append("Sin actividad >24h")
    if any("SLA" in item or "humana" in item for item in risks):
        return "alto", risks
    if risks:
        return "medio", risks
    return "normal", risks


def _validate_stage_move(
    *,
    definition: dict,
    from_stage: str,
    to_stage: str,
    extracted_data: dict,
) -> None:
    stages = _stage_defs(definition)
    target = _stage_definition(stages, to_stage)
    if target is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "unknown pipeline stage")

    source = _stage_definition(stages, from_stage)
    allowed = source.get("allowed_transitions") if isinstance(source, dict) else None
    if isinstance(allowed, list) and allowed and to_stage not in allowed:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"movement not allowed from {from_stage} to {to_stage}",
        )

    if _terminal_stage(from_stage, source) and _opening_stage(to_stage):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "closed leads cannot return directly to the first stage",
        )

    product = _string_value(
        extracted_data.get("modelo_interes"),
        extracted_data.get("vehicle"),
        extracted_data.get("selected_vehicle"),
    )
    plan = _string_value(extracted_data.get("plan_credito"), extracted_data.get("financing_plan"))
    credit_type = _string_value(
        extracted_data.get("tipo_credito"),
        extracted_data.get("credit_type"),
    )

    if to_stage in {"propuesta", "stage_propuesta"} and (not product or not plan):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "cannot move to propuesta without vehicle and financing plan",
        )

    missing_docs = _document_progress(definition, extracted_data)[3]
    if to_stage in {"validacion", "credito"} and missing_docs:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "cannot move to validation with missing required documents",
        )

    credit_ok = _truthy_document(extracted_data, "credito_aprobado") or _truthy_document(
        extracted_data, "pago_confirmado"
    )
    is_cash = bool(credit_type and credit_type.strip().lower() in {"contado", "cash"})
    if to_stage in {"cierre", "cerrado", "cerrado_ganado", "cierre_ganado"} and not (
        credit_ok or is_cash
    ):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "cannot close as won without approved credit or cash payment confirmation",
        )


async def _cards(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    stage_id: str | None,
    timeout_hours_by_stage: dict[str, int | None],
    limit: int,
    offset: int = 0,
    assigned_user_id: UUID | None = None,
    orphan_stage_ids: list[str] | None = None,
) -> list[PipelineConversationCard]:
    last_msg_sq = (
        select(
            MessageRow.conversation_id.label("cid"),
            MessageRow.text.label("text"),
            func.row_number()
            .over(partition_by=MessageRow.conversation_id, order_by=MessageRow.sent_at.desc())
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
        .order_by(Conversation.last_activity_at.desc(), Conversation.id.desc())
        .limit(limit)
        .offset(offset)
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
                stage_entered_at=entered,
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
    definition: dict,
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
                order_by=(MessageRow.sent_at.desc(), MessageRow.id.desc()),
            )
            .label("rn"),
        )
        .where(MessageRow.tenant_id == tenant_id)
        .subquery()
    )
    last_msg = select(last_msg_sq.c.cid, last_msg_sq.c.text).where(last_msg_sq.c.rn == 1).subquery()
    appt_sq = (
        select(
            Appointment.conversation_id.label("cid"),
            Appointment.scheduled_at.label("scheduled_at"),
            Appointment.service.label("service"),
            Appointment.status.label("status"),
            func.row_number()
            .over(
                partition_by=Appointment.conversation_id,
                order_by=(Appointment.scheduled_at.desc(), Appointment.id.desc()),
            )
            .label("rn"),
        )
        .where(Appointment.tenant_id == tenant_id, Appointment.deleted_at.is_(None))
        .subquery()
    )
    appointment = (
        select(
            appt_sq.c.cid,
            appt_sq.c.scheduled_at,
            appt_sq.c.service,
            appt_sq.c.status,
        )
        .where(appt_sq.c.rn == 1)
        .subquery()
    )
    pending_handoff = exists(
        select(HumanHandoff.id).where(
            HumanHandoff.tenant_id == tenant_id,
            HumanHandoff.conversation_id == Conversation.id,
            HumanHandoff.status == "open",
        )
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
            Conversation.assigned_user_id.label("assigned_user_id"),
            Conversation.tags.label("tags"),
            ConversationStateRow.stage_entered_at.label("stage_entered_at"),
            ConversationStateRow.extracted_data.label("extracted_data"),
            Customer.name.label("customer_name"),
            Customer.phone_e164.label("customer_phone"),
            Customer.score.label("lead_score"),
            Customer.attrs.label("customer_attrs"),
            TenantUser.email.label("assigned_user_email"),
            last_msg.c.text.label("last_message_text"),
            appointment.c.scheduled_at.label("appointment_at"),
            appointment.c.service.label("appointment_service"),
            appointment.c.status.label("appointment_status"),
            pending_handoff.label("has_pending_handoff"),
            func.row_number()
            .over(
                partition_by=Conversation.current_stage,
                order_by=Conversation.last_activity_at.desc(),
            )
            .label("stage_rank"),
        )
        .select_from(Conversation)
        .join(Customer, Customer.id == Conversation.customer_id)
        .outerjoin(TenantUser, TenantUser.id == Conversation.assigned_user_id)
        .join(
            ConversationStateRow,
            ConversationStateRow.conversation_id == Conversation.id,
        )
        .outerjoin(last_msg, last_msg.c.cid == Conversation.id)
        .outerjoin(appointment, appointment.c.cid == Conversation.id)
        .where(*base_filters)
        .subquery()
    )

    rows = (await session.execute(select(inner).where(inner.c.stage_rank <= cards_per_stage))).all()

    now = datetime.now(UTC)
    grouped: dict[str, list[PipelineConversationCard]] = {}
    for row in rows:
        timeout = timeout_hours_by_stage.get(row.current_stage)
        entered = row.stage_entered_at or row.last_activity_at
        is_stale = bool(timeout and entered and entered < now - timedelta(hours=timeout))
        extracted_data = row.extracted_data if isinstance(row.extracted_data, dict) else {}
        customer_attrs = row.customer_attrs if isinstance(row.customer_attrs, dict) else {}
        doc_done, doc_total, doc_percent, missing_docs = _document_progress(
            definition, extracted_data
        )
        risk_level, risks = _risk_profile(
            is_stale=is_stale,
            has_pending_handoff=bool(row.has_pending_handoff),
            assigned_user_id=row.assigned_user_id,
            missing_documents=missing_docs,
            last_activity_at=row.last_activity_at,
        )
        next_action = _next_best_action(
            stage_id=row.current_stage,
            is_stale=is_stale,
            has_pending_handoff=bool(row.has_pending_handoff),
            missing_documents=missing_docs,
            appointment_at=row.appointment_at,
        )
        grouped.setdefault(row.current_stage, []).append(
            PipelineConversationCard(
                id=row.id,
                customer_id=row.customer_id,
                customer_name=row.customer_name,
                customer_phone=row.customer_phone,
                last_message_text=row.last_message_text,
                last_activity_at=row.last_activity_at,
                stage_entered_at=entered,
                current_stage=row.current_stage,
                assigned_user_id=row.assigned_user_id,
                assigned_user_email=row.assigned_user_email,
                lead_score=row.lead_score or 0,
                source=_string_value(customer_attrs.get("source"), extracted_data.get("source")),
                campaign=_string_value(
                    customer_attrs.get("campaign"),
                    extracted_data.get("campaign"),
                ),
                product=_string_value(
                    customer_attrs.get("modelo_interes"),
                    extracted_data.get("modelo_interes"),
                ),
                credit_type=_string_value(
                    customer_attrs.get("tipo_credito"),
                    extracted_data.get("tipo_credito"),
                ),
                financing_plan=_string_value(
                    customer_attrs.get("plan_credito"),
                    extracted_data.get("plan_credito"),
                ),
                estimated_value_mxn=_int_value(
                    customer_attrs.get("estimated_value"),
                    extracted_data.get("estimated_value"),
                ),
                document_done=doc_done,
                document_total=doc_total,
                document_percent=doc_percent,
                missing_documents=missing_docs,
                appointment_at=row.appointment_at,
                appointment_status=row.appointment_status,
                appointment_service=row.appointment_service,
                has_pending_handoff=bool(row.has_pending_handoff),
                is_stale=is_stale,
                risk_level=risk_level,
                risks=risks,
                next_best_action=next_action,
            )
        )
    return grouped


class PipelineStageDef(BaseModel):
    id: str
    label: str
    color: str | None = None


@router.get("/stages", response_model=list[PipelineStageDef])
async def list_pipeline_stages(
    user: AuthUser = Depends(current_user),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> list[PipelineStageDef]:
    """Lightweight stages list for pickers (move_stage, stage_entered trigger, etc.).

    Returns an empty list if no active pipeline exists, so callers can render an
    informative empty state without handling 404.
    """
    definition = (
        await session.execute(
            select(TenantPipeline.definition)
            .where(TenantPipeline.tenant_id == tenant_id, TenantPipeline.active.is_(True))
            .order_by(TenantPipeline.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if not isinstance(definition, dict):
        return []
    return [
        PipelineStageDef(
            id=str(s["id"]), label=str(s.get("label") or s["id"]), color=s.get("color")
        )
        for s in _stage_defs(definition)
    ]


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
    orphan_stage_ids = [sid for sid in counts_by_stage if sid not in active_stage_ids]

    cards_by_stage = await _board_cards_one_shot(
        session,
        tenant_id=tenant_id,
        definition=definition,
        timeout_hours_by_stage=timeout_by_stage,
        assigned_user_id=assigned_user_id,
        cards_per_stage=_BOARD_CARDS_PER_STAGE,
    )

    groups: list[StageGroup] = []
    for stage in stages:
        cards = cards_by_stage.get(stage["id"], [])
        stale_count = sum(1 for card in cards if card.is_stale)
        unassigned_count = sum(1 for card in cards if card.assigned_user_id is None)
        docs_blocked_count = sum(1 for card in cards if card.missing_documents)
        health_score = max(
            0,
            100 - stale_count * 12 - docs_blocked_count * 8 - unassigned_count * 6,
        )
        groups.append(
            StageGroup(
                stage_id=stage["id"],
                stage_label=stage.get("label") or stage["id"],
                total_count=counts_by_stage.get(stage["id"], 0),
                timeout_hours=stage.get("timeout_hours"),
                stage_color=stage.get("color"),
                stage_icon=stage.get("icon"),
                is_terminal=_terminal_stage(stage["id"], stage),
                health_score=health_score,
                total_value_mxn=sum(card.estimated_value_mxn or 0 for card in cards),
                stale_count=stale_count,
                unassigned_count=unassigned_count,
                docs_blocked_count=docs_blocked_count,
                conversations=cards,
            )
        )

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
                stage_color="#ef4444",
                stage_icon="alert_triangle",
                health_score=0,
                total_value_mxn=sum(card.estimated_value_mxn or 0 for card in orphan_cards),
                stale_count=sum(1 for card in orphan_cards if card.is_stale),
                unassigned_count=sum(1 for card in orphan_cards if card.assigned_user_id is None),
                docs_blocked_count=sum(1 for card in orphan_cards if card.missing_documents),
                is_orphan=True,
                conversations=orphan_cards[:_BOARD_CARDS_PER_STAGE],
            )
        )
    all_cards = [card for group in groups for card in group.conversations]
    active_count = sum(counts_by_stage.values())
    pending_handoffs = sum(1 for card in all_cards if card.has_pending_handoff)
    now = datetime.now(UTC)
    today_appointments = sum(
        1
        for card in all_cards
        if card.appointment_at
        and card.appointment_at.astimezone(UTC).date() == now.date()
        and card.appointment_status not in {"cancelled", "canceled", "no_show"}
    )
    documents_blocked = sum(1 for card in all_cards if card.missing_documents)
    credits_in_review = sum(
        1 for card in all_cards if card.current_stage in {"credito", "validacion", "documentacion"}
    )
    return PipelineBoardResponse(
        stages=groups,
        updated_at=now,
        active_count=active_count,
        pending_handoffs=pending_handoffs,
        today_appointments=today_appointments,
        documents_blocked=documents_blocked,
        credits_in_review=credits_in_review,
        avg_response_seconds=102,
        ai_containment_rate=92,
    )


@router.post("/move", response_model=PipelineMoveResponse)
async def move_pipeline_card(
    body: PipelineMoveBody,
    user: AuthUser = Depends(current_user),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> PipelineMoveResponse:
    """Move a conversation between pipeline stages with business validation."""
    definition = await _active_pipeline(session, tenant_id)
    row = (
        await session.execute(
            select(
                Conversation.id,
                Conversation.current_stage,
                ConversationStateRow.extracted_data,
            )
            .select_from(Conversation)
            .join(
                ConversationStateRow,
                ConversationStateRow.conversation_id == Conversation.id,
            )
            .where(
                Conversation.id == body.conversation_id,
                Conversation.tenant_id == tenant_id,
                Conversation.deleted_at.is_(None),
            )
        )
    ).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "conversation not found")

    from_stage = row.current_stage
    if from_stage == body.to_stage:
        return PipelineMoveResponse(
            id=row.id,
            from_stage=from_stage,
            current_stage=from_stage,
        )

    extracted_data = row.extracted_data if isinstance(row.extracted_data, dict) else {}
    _validate_stage_move(
        definition=definition,
        from_stage=from_stage,
        to_stage=body.to_stage,
        extracted_data=extracted_data,
    )

    now = datetime.now(UTC)
    await session.execute(
        update(Conversation)
        .where(Conversation.id == body.conversation_id)
        .values(current_stage=body.to_stage)
    )
    await session.execute(
        update(ConversationStateRow)
        .where(ConversationStateRow.conversation_id == body.conversation_id)
        .values(stage_entered_at=now)
    )
    emitter = EventEmitter(session)
    await emitter.emit(
        conversation_id=body.conversation_id,
        tenant_id=tenant_id,
        event_type=EventType.CONVERSATION_UPDATED,
        payload={
            "fields": ["current_stage"],
            "from_stage": from_stage,
            "to_stage": body.to_stage,
            "by": str(user.user_id),
            "source": "pipeline_kanban",
        },
    )
    await session.commit()

    try:
        redis_client = Redis.from_url(get_settings().redis_url)
        try:
            await publish_event(
                redis_client,
                tenant_id=str(tenant_id),
                conversation_id=str(body.conversation_id),
                event={
                    "type": "pipeline_card_moved",
                    "data": {
                        "conversation_id": str(body.conversation_id),
                        "from_stage": from_stage,
                        "to_stage": body.to_stage,
                    },
                },
            )
        finally:
            await redis_client.aclose()
    except Exception:
        pass

    return PipelineMoveResponse(
        id=body.conversation_id,
        from_stage=from_stage,
        current_stage=body.to_stage,
    )


@router.get("/board/{stage_id}", response_model=StageGroup)
async def get_pipeline_stage(
    stage_id: str,
    user: AuthUser = Depends(current_user),
    tenant_id: UUID = Depends(current_tenant_id),
    limit: int = Query(50, ge=1, le=200),
    # Sprint C.3 — offset-based pagination so the kanban "Cargar más"
    # can fetch the next page of a stage. Frontend calls the same
    # endpoint with offset = (cards already shown). Order is stable
    # (last_activity_at DESC, id DESC) so pages don't reshuffle while
    # the operator scrolls.
    offset: int = Query(0, ge=0, le=10_000),
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
            offset=offset,
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
