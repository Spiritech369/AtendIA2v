"""Customers Command Center.

Tenant-scoped lightweight CRM with operational scoring, risk detection,
next-best-actions, timeline, documents, messages, CSV import/export and demo
data for the AtendIA operator dashboard.
"""

from __future__ import annotations

import csv
import io
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy import select as _sa_select
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.api._audit import emit_admin_event
from atendia.api._auth_helpers import AuthUser
from atendia.api._deps import current_tenant_id, current_user
from atendia.db.models.conversation import Conversation, ConversationStateRow
from atendia.db.models.customer import (
    Customer,
    CustomerAIReviewItem,
    CustomerDocument,
    CustomerNextBestAction,
    CustomerRisk,
    CustomerScore,
    CustomerTimelineEvent,
)
from atendia.db.models.event import EventRow
from atendia.db.models.message import MessageRow
from atendia.db.models.tenant import Tenant as _Tenant, TenantUser
from atendia.db.session import get_db_session

router = APIRouter()
dashboard_router = APIRouter()
risks_router = APIRouter()
ai_review_router = APIRouter()
documents_router = APIRouter()

CLIENT_STAGES = {
    "new": "Nuevo",
    "in_conversation": "En conversacion",
    "qualified": "Calificado",
    "negotiation": "Negociacion",
    "documentation": "Documentacion",
    "pending_handoff": "Handoff pendiente",
    "closed_won": "Cerrado ganado",
    "closed_lost": "Cerrado perdido",
    "lost_risk": "Riesgo perdido",
}
SLA_HOURS = {
    "new": 1,
    "in_conversation": 4,
    "qualified": 6,
    "negotiation": 2,
    "documentation": 8,
    "pending_handoff": 0.5,
}
DOCUMENT_TYPES = [
    ("ine_front", "INE frente"),
    ("ine_back", "INE reverso"),
    ("proof_of_address", "Comprobante de domicilio"),
    ("bank_statement", "Estado de cuenta"),
    ("payroll_receipt", "Recibo de nomina"),
    ("income_proof", "Comprobante de ingresos"),
    ("imss_resolution", "Resolucion IMSS"),
]
ACTION_LABELS = {
    "send_follow_up": "Enviar seguimiento",
    "request_documents": "Solicitar documentos",
    "assign_seller": "Asignar vendedor",
    "call_now": "Llamar ahora",
    "review_conversation": "Revisar conversacion",
    "escalate_to_human": "Escalar a humano",
    "move_to_negotiation": "Mover a negociacion",
    "mark_lost_risk": "Marcar riesgo perdido",
    "reassign": "Reasignar",
    "schedule_appointment": "Agendar cita",
}


class CustomerScoreOut(BaseModel):
    id: UUID
    customer_id: UUID
    tenant_id: UUID
    total_score: int
    intent_score: int
    activity_score: int
    documentation_score: int
    data_quality_score: int
    conversation_engagement_score: int
    stage_progress_score: int
    abandonment_risk_score: int
    explanation: dict
    calculated_at: datetime


class CustomerRiskOut(BaseModel):
    id: UUID
    tenant_id: UUID
    customer_id: UUID
    risk_type: str
    severity: str
    reason: str
    recommended_action: str
    status: str
    created_at: datetime
    resolved_at: datetime | None


class NextBestActionOut(BaseModel):
    id: UUID
    tenant_id: UUID
    customer_id: UUID
    action_type: str
    priority: int
    reason: str
    confidence: float
    suggested_message: str | None
    status: str
    expires_at: datetime | None
    created_at: datetime
    executed_at: datetime | None


class TimelineEventOut(BaseModel):
    id: UUID
    tenant_id: UUID
    customer_id: UUID
    event_type: str
    title: str
    description: str | None
    actor_type: str
    actor_id: UUID | None
    metadata_json: dict
    created_at: datetime


class CustomerDocumentOut(BaseModel):
    id: UUID
    tenant_id: UUID
    customer_id: UUID
    document_type: str
    label: str
    status: str
    file_url: str | None
    uploaded_at: datetime | None
    reviewed_at: datetime | None
    rejection_reason: str | None
    created_at: datetime
    updated_at: datetime


class ConversationMessageOut(BaseModel):
    id: UUID
    conversation_id: UUID
    direction: str
    sender_type: str
    body: str
    confidence_score: float | None
    intent_detected: str | None
    objection_detected: str | None
    related_workflow: str | None
    sent_at: datetime


class AIReviewItemOut(BaseModel):
    id: UUID
    tenant_id: UUID
    customer_id: UUID
    conversation_id: UUID | None
    issue_type: str
    severity: str
    title: str
    description: str | None
    ai_summary: str | None
    confidence: float | None
    risky_output_flag: bool
    human_review_required: bool
    status: str
    feedback_status: str | None
    created_at: datetime
    resolved_at: datetime | None


class CustomerListItem(BaseModel):
    id: UUID
    tenant_id: UUID
    phone_e164: str
    name: str | None
    email: str | None = None
    score: int = 0
    health_score: int = 0
    status: str = "active"
    stage: str = "new"
    effective_stage: str | None = None
    source: str | None = None
    tags: list[str] = []
    assigned_user_id: UUID | None = None
    assigned_user_email: str | None = None
    last_activity_at: datetime | None = None
    created_at: datetime
    updated_at: datetime | None = None
    conversation_count: int
    risk_level: str = "low"
    sla_status: str = "on_track"
    next_best_action: str | None = None
    ai_summary: str | None = None
    ai_insight_reason: str | None = None
    ai_confidence: float | None = None
    documents_status: str = "missing"


class CustomerListResponse(BaseModel):
    items: list[CustomerListItem]


class ConversationSummary(BaseModel):
    id: UUID
    current_stage: str
    status: str
    last_activity_at: datetime
    total_cost_usd: Decimal


class CustomerDetail(CustomerListItem):
    attrs: dict
    conversations: list[ConversationSummary]
    last_extracted_data: dict
    total_cost_usd: Decimal
    latest_score: CustomerScoreOut | None = None
    open_risks: list[CustomerRiskOut] = []
    next_best_actions: list[NextBestActionOut] = []
    timeline: list[TimelineEventOut] = []
    documents: list[CustomerDocumentOut] = []
    messages: list[ConversationMessageOut] = []
    ai_review_items: list[AIReviewItemOut] = []


class CustomerPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = None
    email: str | None = Field(default=None, max_length=160)
    attrs: dict | None = None
    status: str | None = None
    stage: str | None = None
    source: str | None = None
    tags: list[str] | None = None
    assigned_user_id: UUID | None = None

    @field_validator("email")
    @classmethod
    def _strip_email(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @field_validator("stage")
    @classmethod
    def _valid_stage(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        if normalized not in CLIENT_STAGES:
            raise ValueError(f"stage must be one of: {', '.join(CLIENT_STAGES)}")
        return normalized


class CustomerCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    phone_e164: str
    name: str | None = None
    email: str | None = None
    source: str | None = None
    tags: list[str] = []
    stage: str = "new"
    attrs: dict = {}

    @field_validator("stage")
    @classmethod
    def _valid_stage(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in CLIENT_STAGES:
            raise ValueError(f"stage must be one of: {', '.join(CLIENT_STAGES)}")
        return normalized


class ScorePatch(BaseModel):
    score: int = Field(ge=0, le=100)


class AssignBody(BaseModel):
    assigned_user_id: UUID | None


class ChangeStageBody(BaseModel):
    stage: str

    @field_validator("stage")
    @classmethod
    def _valid_stage(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in CLIENT_STAGES:
            raise ValueError(f"stage must be one of: {', '.join(CLIENT_STAGES)}")
        return normalized


class TimelineCreate(BaseModel):
    event_type: str
    title: str
    description: str | None = None
    actor_type: str = "human"
    metadata_json: dict = {}


class DocumentCreate(BaseModel):
    document_type: str
    label: str | None = None
    status: str = "received"
    file_url: str | None = None
    rejection_reason: str | None = None


class DocumentPatch(BaseModel):
    status: str | None = None
    file_url: str | None = None
    rejection_reason: str | None = None


class MessageCreate(BaseModel):
    body: str
    sender_type: str = "human"
    confidence_score: float | None = None
    intent_detected: str | None = None
    objection_detected: str | None = None
    related_workflow: str | None = None


class CustomerImportResult(BaseModel):
    created: int
    updated: int
    errors: list[str]


class CustomerImportPreviewRow(BaseModel):
    row: int
    phone: str
    name: str | None
    email: str | None
    score: int | None
    will: str


class CustomerImportPreview(BaseModel):
    valid_rows: list[CustomerImportPreviewRow]
    errors: list[str]
    total: int


class CustomerKpis(BaseModel):
    total_clients: int
    clients_needing_attention: int
    high_score_without_followup: int
    at_risk_clients: int
    unassigned_clients: int
    documentation_pending: int
    active_negotiations: int
    ai_review_open: int


class RadarItem(BaseModel):
    title: str
    count: int
    severity: str
    affected_client_ids: list[UUID]
    recommended_action: str
    action_link: str


class RiskRadarResponse(BaseModel):
    items: list[RadarItem]
    updated_at: datetime


class AIReviewQueueResponse(BaseModel):
    items: list[AIReviewItemOut]


def _now() -> datetime:
    return datetime.now(UTC)


def _hours_since(value: datetime | None, now: datetime | None = None) -> float:
    if value is None:
        return 999.0
    ref = now or _now()
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return max(0.0, (ref - value.astimezone(UTC)).total_seconds() / 3600)


def _risk_rank(level: str) -> int:
    return {"low": 1, "medium": 2, "high": 3, "critical": 4}.get(level, 0)


def _sla_status(
    stage: str, last_activity_at: datetime | None, created_at: datetime | None, now: datetime
) -> str:
    hours = _hours_since(last_activity_at or created_at, now)
    limit = SLA_HOURS.get(stage, 8)
    if hours >= limit:
        return "breached"
    if hours >= limit * 0.75:
        return "attention_soon"
    return "on_track"


def _message_sender(direction: str, metadata: dict | None) -> str:
    if metadata and metadata.get("sender_type"):
        return str(metadata["sender_type"])
    if direction == "inbound":
        return "client"
    if direction == "system":
        return "system"
    return "ai"


def _message_out(row: MessageRow) -> ConversationMessageOut:
    meta = row.metadata_json or {}
    return ConversationMessageOut(
        id=row.id,
        conversation_id=row.conversation_id,
        direction=row.direction,
        sender_type=_message_sender(row.direction, meta),
        body=row.text,
        confidence_score=meta.get("confidence_score"),
        intent_detected=meta.get("intent_detected"),
        objection_detected=meta.get("objection_detected"),
        related_workflow=meta.get("related_workflow"),
        sent_at=row.sent_at,
    )


def _score_out(row: CustomerScore) -> CustomerScoreOut:
    return CustomerScoreOut(
        id=row.id,
        customer_id=row.customer_id,
        tenant_id=row.tenant_id,
        total_score=row.total_score,
        intent_score=row.intent_score,
        activity_score=row.activity_score,
        documentation_score=row.documentation_score,
        data_quality_score=row.data_quality_score,
        conversation_engagement_score=row.conversation_engagement_score,
        stage_progress_score=row.stage_progress_score,
        abandonment_risk_score=row.abandonment_risk_score,
        explanation=row.explanation or {},
        calculated_at=row.calculated_at,
    )


def _risk_out(row: CustomerRisk) -> CustomerRiskOut:
    return CustomerRiskOut(
        id=row.id,
        tenant_id=row.tenant_id,
        customer_id=row.customer_id,
        risk_type=row.risk_type,
        severity=row.severity,
        reason=row.reason,
        recommended_action=row.recommended_action,
        status=row.status,
        created_at=row.created_at,
        resolved_at=row.resolved_at,
    )


def _action_out(row: CustomerNextBestAction) -> NextBestActionOut:
    return NextBestActionOut(
        id=row.id,
        tenant_id=row.tenant_id,
        customer_id=row.customer_id,
        action_type=row.action_type,
        priority=row.priority,
        reason=row.reason,
        confidence=row.confidence,
        suggested_message=row.suggested_message,
        status=row.status,
        expires_at=row.expires_at,
        created_at=row.created_at,
        executed_at=row.executed_at,
    )


def _timeline_out(row: CustomerTimelineEvent) -> TimelineEventOut:
    return TimelineEventOut(
        id=row.id,
        tenant_id=row.tenant_id,
        customer_id=row.customer_id,
        event_type=row.event_type,
        title=row.title,
        description=row.description,
        actor_type=row.actor_type,
        actor_id=row.actor_id,
        metadata_json=row.metadata_json or {},
        created_at=row.created_at,
    )


def _document_out(row: CustomerDocument) -> CustomerDocumentOut:
    return CustomerDocumentOut(
        id=row.id,
        tenant_id=row.tenant_id,
        customer_id=row.customer_id,
        document_type=row.document_type,
        label=row.label,
        status=row.status,
        file_url=row.file_url,
        uploaded_at=row.uploaded_at,
        reviewed_at=row.reviewed_at,
        rejection_reason=row.rejection_reason,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _ai_review_out(row: CustomerAIReviewItem) -> AIReviewItemOut:
    return AIReviewItemOut(
        id=row.id,
        tenant_id=row.tenant_id,
        customer_id=row.customer_id,
        conversation_id=row.conversation_id,
        issue_type=row.issue_type,
        severity=row.severity,
        title=row.title,
        description=row.description,
        ai_summary=row.ai_summary,
        confidence=row.confidence,
        risky_output_flag=row.risky_output_flag,
        human_review_required=row.human_review_required,
        status=row.status,
        feedback_status=row.feedback_status,
        created_at=row.created_at,
        resolved_at=row.resolved_at,
    )


def _stage_progress(stage: str) -> int:
    order = list(CLIENT_STAGES.keys())
    try:
        return int((order.index(stage) + 1) / len(order) * 100)
    except ValueError:
        return 30


def _document_score(docs: list[CustomerDocument]) -> tuple[int, str]:
    if not docs:
        return 0, "Sin checklist documental."
    good = sum(1 for d in docs if d.status in {"received", "approved"})
    rejected = sum(1 for d in docs if d.status == "rejected")
    score = int((good / len(docs)) * 100) - rejected * 10
    status_text = f"{good}/{len(docs)} documentos recibidos"
    if rejected:
        status_text += f", {rejected} rechazado(s)"
    return max(0, min(100, score)), status_text


def _data_quality_score(customer: Customer) -> tuple[int, list[str]]:
    missing: list[str] = []
    points = 25
    if customer.name:
        points += 20
    else:
        missing.append("nombre")
    if customer.email:
        points += 15
    else:
        missing.append("email")
    attrs = customer.attrs or {}
    for key in ("credit_type", "budget", "vehicle_interest", "city"):
        if attrs.get(key):
            points += 10
        else:
            missing.append(key)
    return max(0, min(100, points)), missing


def calculate_customer_score(
    customer: Customer, docs: list[CustomerDocument], now: datetime | None = None
) -> CustomerScore:
    ref = now or _now()
    attrs = customer.attrs or {}
    intent_score = int(attrs.get("intent_score") or 50)
    hours_idle = _hours_since(customer.last_activity_at or customer.created_at, ref)
    activity_score = (
        100 if hours_idle < 2 else 82 if hours_idle < 8 else 55 if hours_idle < 24 else 25
    )
    documentation_score, doc_reason = _document_score(docs)
    data_quality_score, missing = _data_quality_score(customer)
    conversation_engagement_score = int(
        attrs.get("engagement_score") or (78 if customer.last_activity_at else 35)
    )
    stage_progress_score = _stage_progress(customer.stage)
    abandonment_risk_score = 0 if hours_idle < 8 else 18 if hours_idle < 24 else 35
    total = int(
        intent_score * 0.22
        + activity_score * 0.18
        + documentation_score * 0.16
        + data_quality_score * 0.14
        + conversation_engagement_score * 0.14
        + stage_progress_score * 0.16
        - abandonment_risk_score * 0.22
    )
    total = max(0, min(100, total))
    explanation = {
        "summary": f"Score {total}/100 por intencion {intent_score}, actividad {activity_score} y documentos {documentation_score}.",
        "documentation": doc_reason,
        "missing_data": missing,
        "idle_hours": round(hours_idle, 1),
        "stage": customer.stage,
    }
    return CustomerScore(
        tenant_id=customer.tenant_id,
        customer_id=customer.id,
        total_score=total,
        intent_score=intent_score,
        activity_score=activity_score,
        documentation_score=documentation_score,
        data_quality_score=data_quality_score,
        conversation_engagement_score=conversation_engagement_score,
        stage_progress_score=stage_progress_score,
        abandonment_risk_score=abandonment_risk_score,
        explanation=explanation,
        calculated_at=ref,
    )


def detect_customer_risks(
    customer: Customer, docs: list[CustomerDocument], now: datetime | None = None
) -> list[dict]:
    ref = now or _now()
    risks: list[dict] = []
    hours_idle = _hours_since(customer.last_activity_at or customer.created_at, ref)
    doc_missing = [d for d in docs if d.status in {"missing", "rejected"}]
    sla = _sla_status(customer.stage, customer.last_activity_at, customer.created_at, ref)
    attrs = customer.attrs or {}

    if hours_idle > 8:
        risks.append(
            {
                "risk_type": "idle_too_long",
                "severity": "high" if hours_idle > 24 else "medium",
                "reason": f"Cliente sin actividad por {hours_idle:.0f} h.",
                "recommended_action": "Enviar seguimiento con contexto y proxima pregunta clara.",
            }
        )
    if customer.health_score > 80 and hours_idle > 8:
        risks.append(
            {
                "risk_type": "high_score_without_followup",
                "severity": "high",
                "reason": "Cliente de alto potencial sin seguimiento reciente.",
                "recommended_action": "Priorizar seguimiento humano hoy.",
            }
        )
    if customer.stage == "negotiation" and not customer.assigned_user_id:
        risks.append(
            {
                "risk_type": "negotiation_without_owner",
                "severity": "critical",
                "reason": "Negociacion activa sin vendedor asignado.",
                "recommended_action": "Asignar asesor y abrir conversacion.",
            }
        )
    if customer.stage == "documentation" and doc_missing:
        risks.append(
            {
                "risk_type": "documentation_incomplete",
                "severity": "medium",
                "reason": f"Faltan {len(doc_missing)} documentos para avanzar.",
                "recommended_action": "Solicitar documentos faltantes por WhatsApp.",
            }
        )
    if sla == "breached":
        risks.append(
            {
                "risk_type": "sla_breached",
                "severity": "critical",
                "reason": "SLA de la etapa vencido.",
                "recommended_action": "Escalar a humano y registrar resolucion.",
            }
        )
    data_score, missing = _data_quality_score(customer)
    if data_score < 70:
        risks.append(
            {
                "risk_type": "missing_required_fields",
                "severity": "medium",
                "reason": "Datos requeridos incompletos: " + ", ".join(missing[:4]),
                "recommended_action": "Completar ficha antes de cotizar.",
            }
        )
    if (customer.ai_confidence or 1) < 0.62:
        risks.append(
            {
                "risk_type": "ai_low_confidence",
                "severity": "high",
                "reason": "Ultima accion IA con baja confianza.",
                "recommended_action": "Enviar a revision IA antes de continuar automatizacion.",
            }
        )
    if customer.stage == "pending_handoff" and hours_idle > 0.5:
        risks.append(
            {
                "risk_type": "handoff_pending_too_long",
                "severity": "critical",
                "reason": "Handoff humano pendiente por mas de 30 minutos.",
                "recommended_action": "Tomar conversacion o reasignar al supervisor.",
            }
        )
    if attrs.get("objections"):
        risks.append(
            {
                "risk_type": "objections_detected",
                "severity": "medium",
                "reason": "Objeciones detectadas: " + ", ".join(attrs.get("objections", [])[:3]),
                "recommended_action": "Responder objecion principal con evidencia.",
            }
        )
    return risks


def recommend_next_actions(
    customer: Customer, risks: list[dict], now: datetime | None = None
) -> list[dict]:
    ref = now or _now()
    risk_types = {r["risk_type"] for r in risks}
    hours_idle = _hours_since(customer.last_activity_at or customer.created_at, ref)
    actions: list[dict] = []

    def add(
        action_type: str, priority: int, reason: str, confidence: float, message: str | None = None
    ) -> None:
        actions.append(
            {
                "action_type": action_type,
                "priority": priority,
                "reason": reason,
                "confidence": confidence,
                "suggested_message": message,
                "expires_at": ref + timedelta(hours=8),
            }
        )

    if customer.health_score > 80 and hours_idle > 8:
        add(
            "send_follow_up",
            92,
            "Cliente con alto score sin seguimiento en mas de 8 h.",
            0.91,
            "Hola, sigo al pendiente. Te ayudo a avanzar con la aprobacion y resolver cualquier duda.",
        )
    if customer.stage == "negotiation" and not customer.assigned_user_id:
        add("assign_seller", 96, "Negociacion activa sin propietario.", 0.95)
    if customer.stage == "documentation" and "documentation_incomplete" in risk_types:
        add(
            "request_documents",
            88,
            "Documentos incompletos bloquean el avance.",
            0.89,
            "Para avanzar, me compartes INE, comprobante de domicilio y recibos de nomina?",
        )
    if "sla_breached" in risk_types:
        add("escalate_to_human", 100, "SLA vencido requiere intervencion inmediata.", 0.94)
    if _risk_rank(customer.risk_level) >= 3 and hours_idle > 24:
        add("call_now", 98, "Riesgo alto e inactividad mayor a 24 h.", 0.87)
    if customer.stage == "qualified":
        add("move_to_negotiation", 70, "Cliente calificado listo para propuesta.", 0.76)
    if not actions:
        add(
            "review_conversation",
            45,
            "Mantener monitoreo y revisar contexto antes del siguiente contacto.",
            0.64,
        )
    return sorted(actions, key=lambda x: x["priority"], reverse=True)[:3]


async def _sync_customer_ops(
    session: AsyncSession, customer: Customer, *, actor_user_id: UUID | None = None
) -> CustomerScore:
    docs = (
        (
            await session.execute(
                select(CustomerDocument).where(
                    CustomerDocument.customer_id == customer.id,
                    CustomerDocument.tenant_id == customer.tenant_id,
                )
            )
        )
        .scalars()
        .all()
    )
    ref = _now()
    score = calculate_customer_score(customer, docs, ref)
    customer.score = score.total_score
    customer.health_score = score.total_score
    customer.sla_status = _sla_status(
        customer.stage, customer.last_activity_at, customer.created_at, ref
    )
    customer.documents_status = (
        "complete"
        if docs and all(d.status in {"received", "approved"} for d in docs)
        else "pending"
    )
    customer.ai_insight_reason = score.explanation.get("summary")

    await session.execute(
        update(CustomerRisk)
        .where(CustomerRisk.customer_id == customer.id, CustomerRisk.status == "open")
        .values(status="resolved", resolved_at=ref)
    )
    await session.execute(
        update(CustomerNextBestAction)
        .where(
            CustomerNextBestAction.customer_id == customer.id,
            CustomerNextBestAction.status == "active",
        )
        .values(status="expired")
    )
    session.add(score)

    risk_defs = detect_customer_risks(customer, docs, ref)
    worst = "low"
    for item in risk_defs:
        if _risk_rank(item["severity"]) > _risk_rank(worst):
            worst = item["severity"]
        session.add(CustomerRisk(tenant_id=customer.tenant_id, customer_id=customer.id, **item))
    customer.risk_level = worst

    action_defs = recommend_next_actions(customer, risk_defs, ref)
    for item in action_defs:
        session.add(
            CustomerNextBestAction(tenant_id=customer.tenant_id, customer_id=customer.id, **item)
        )
    customer.next_best_action = action_defs[0]["action_type"] if action_defs else None

    session.add(
        CustomerTimelineEvent(
            tenant_id=customer.tenant_id,
            customer_id=customer.id,
            event_type="ai_recommendation_generated",
            title="Score y proxima accion recalculados",
            description=customer.ai_insight_reason,
            actor_type="ai",
            actor_id=actor_user_id,
            metadata_json={
                "score": score.total_score,
                "risks": len(risk_defs),
                "actions": len(action_defs),
            },
        )
    )
    return score


async def _verify_customer(customer_id: UUID, tenant_id: UUID, session: AsyncSession) -> Customer:
    customer = (
        await session.execute(
            select(Customer).where(Customer.id == customer_id, Customer.tenant_id == tenant_id)
        )
    ).scalar_one_or_none()
    if customer is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "customer not found")
    return customer


async def _latest_conversation(
    customer_id: UUID, tenant_id: UUID, session: AsyncSession
) -> Conversation | None:
    return (
        await session.execute(
            select(Conversation)
            .where(
                Conversation.customer_id == customer_id,
                Conversation.tenant_id == tenant_id,
                Conversation.deleted_at.is_(None),
            )
            .order_by(Conversation.last_activity_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def _ensure_conversation(customer: Customer, session: AsyncSession) -> Conversation:
    conv = await _latest_conversation(customer.id, customer.tenant_id, session)
    if conv:
        return conv
    conv = Conversation(
        tenant_id=customer.tenant_id,
        customer_id=customer.id,
        channel="whatsapp_meta",
        status="active",
        current_stage=customer.stage,
        assigned_user_id=customer.assigned_user_id,
        last_activity_at=customer.last_activity_at or _now(),
    )
    session.add(conv)
    await session.flush()
    session.add(ConversationStateRow(conversation_id=conv.id, extracted_data=customer.attrs or {}))
    return conv


def _customer_item_from_row(row) -> CustomerListItem:
    effective_stage = row.effective_stage or row.stage
    last_activity = row.effective_last_activity_at or row.last_activity_at or row.created_at
    return CustomerListItem(
        id=row.id,
        tenant_id=row.tenant_id,
        phone_e164=row.phone_e164,
        name=row.name,
        email=row.email,
        score=row.score or row.health_score or 0,
        health_score=row.health_score or row.score or 0,
        status=row.status,
        stage=row.stage,
        effective_stage=effective_stage,
        source=row.source,
        tags=row.tags or [],
        assigned_user_id=row.assigned_user_id or row.latest_assigned_user_id,
        assigned_user_email=row.assigned_user_email,
        last_activity_at=last_activity,
        created_at=row.created_at,
        updated_at=row.updated_at,
        conversation_count=row.conversation_count,
        risk_level=row.risk_level,
        sla_status=row.sla_status,
        next_best_action=row.next_best_action,
        ai_summary=row.ai_summary,
        ai_insight_reason=row.ai_insight_reason,
        ai_confidence=row.ai_confidence,
        documents_status=row.documents_status,
    )


async def _customer_list_base(
    session: AsyncSession,
    tenant_id: UUID,
    *,
    q: str | None = None,
    stage: str | None = None,
    assigned_user_id: UUID | None = None,
    risk_level: str | None = None,
    sla_status: str | None = None,
    sort_by: str = "created_at",
    sort_dir: str = "desc",
    limit: int = 50,
) -> list[CustomerListItem]:
    conv_count = (
        select(Conversation.customer_id, func.count(Conversation.id).label("n"))
        .where(Conversation.tenant_id == tenant_id, Conversation.deleted_at.is_(None))
        .group_by(Conversation.customer_id)
        .subquery()
    )
    latest_conv_sq = (
        select(
            Conversation.customer_id.label("customer_id"),
            Conversation.current_stage.label("effective_stage"),
            Conversation.last_activity_at.label("last_activity_at"),
            Conversation.assigned_user_id.label("assigned_user_id"),
            func.row_number()
            .over(
                partition_by=Conversation.customer_id, order_by=Conversation.last_activity_at.desc()
            )
            .label("rn"),
        )
        .where(Conversation.tenant_id == tenant_id, Conversation.deleted_at.is_(None))
        .subquery()
    )
    latest = select(latest_conv_sq).where(latest_conv_sq.c.rn == 1).subquery()
    assigned_id = func.coalesce(Customer.assigned_user_id, latest.c.assigned_user_id)
    last_activity = func.coalesce(
        Customer.last_activity_at, latest.c.last_activity_at, Customer.created_at
    )

    stmt = (
        select(
            Customer.id,
            Customer.tenant_id,
            Customer.phone_e164,
            Customer.name,
            Customer.email,
            Customer.score,
            Customer.health_score,
            Customer.status,
            Customer.stage,
            Customer.source,
            Customer.tags,
            Customer.assigned_user_id,
            Customer.last_activity_at,
            Customer.created_at,
            Customer.updated_at,
            Customer.risk_level,
            Customer.sla_status,
            Customer.next_best_action,
            Customer.ai_summary,
            Customer.ai_insight_reason,
            Customer.ai_confidence,
            Customer.documents_status,
            func.coalesce(conv_count.c.n, 0).label("conversation_count"),
            latest.c.effective_stage,
            latest.c.last_activity_at.label("effective_last_activity_at"),
            latest.c.assigned_user_id.label("latest_assigned_user_id"),
            TenantUser.email.label("assigned_user_email"),
        )
        .select_from(Customer)
        .outerjoin(conv_count, conv_count.c.customer_id == Customer.id)
        .outerjoin(latest, latest.c.customer_id == Customer.id)
        .outerjoin(TenantUser, TenantUser.id == assigned_id)
        .where(Customer.tenant_id == tenant_id)
        .limit(limit)
    )
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            or_(
                Customer.phone_e164.ilike(like),
                Customer.name.ilike(like),
                Customer.email.ilike(like),
            )
        )
    if stage:
        stmt = stmt.where(or_(Customer.stage == stage, latest.c.effective_stage == stage))
    if assigned_user_id:
        stmt = stmt.where(assigned_id == assigned_user_id)
    if risk_level:
        stmt = stmt.where(Customer.risk_level == risk_level)
    if sla_status:
        stmt = stmt.where(Customer.sla_status == sla_status)

    sort_col = {
        "name": Customer.name,
        "last_activity": last_activity,
        "score": Customer.health_score,
        "created_at": Customer.created_at,
        "risk": Customer.risk_level,
        "sla": Customer.sla_status,
    }[sort_by]
    stmt = stmt.order_by(
        sort_col.asc().nullslast() if sort_dir == "asc" else sort_col.desc().nullslast()
    )
    rows = (await session.execute(stmt)).all()
    return [_customer_item_from_row(r) for r in rows]


async def _detail_payload(
    customer: Customer, tenant_id: UUID, session: AsyncSession
) -> CustomerDetail:
    list_item = (await _customer_list_base(session, tenant_id, q=customer.phone_e164, limit=1))[0]
    convs_rows = (
        await session.execute(
            select(
                Conversation.id,
                Conversation.current_stage,
                Conversation.status,
                Conversation.last_activity_at,
                ConversationStateRow.total_cost_usd,
                ConversationStateRow.extracted_data,
            )
            .select_from(Conversation)
            .outerjoin(
                ConversationStateRow, ConversationStateRow.conversation_id == Conversation.id
            )
            .where(Conversation.customer_id == customer.id, Conversation.tenant_id == tenant_id)
            .order_by(Conversation.last_activity_at.desc())
        )
    ).all()
    conversations = [
        ConversationSummary(
            id=r.id,
            current_stage=r.current_stage,
            status=r.status,
            last_activity_at=r.last_activity_at,
            total_cost_usd=r.total_cost_usd or Decimal("0"),
        )
        for r in convs_rows
    ]
    latest_score = (
        await session.execute(
            select(CustomerScore)
            .where(CustomerScore.customer_id == customer.id, CustomerScore.tenant_id == tenant_id)
            .order_by(CustomerScore.calculated_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    risks = (
        (
            await session.execute(
                select(CustomerRisk)
                .where(
                    CustomerRisk.customer_id == customer.id,
                    CustomerRisk.tenant_id == tenant_id,
                    CustomerRisk.status == "open",
                )
                .order_by(CustomerRisk.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    actions = (
        (
            await session.execute(
                select(CustomerNextBestAction)
                .where(
                    CustomerNextBestAction.customer_id == customer.id,
                    CustomerNextBestAction.tenant_id == tenant_id,
                    CustomerNextBestAction.status == "active",
                )
                .order_by(
                    CustomerNextBestAction.priority.desc(), CustomerNextBestAction.created_at.desc()
                )
                .limit(5)
            )
        )
        .scalars()
        .all()
    )
    timeline = (
        (
            await session.execute(
                select(CustomerTimelineEvent)
                .where(
                    CustomerTimelineEvent.customer_id == customer.id,
                    CustomerTimelineEvent.tenant_id == tenant_id,
                )
                .order_by(CustomerTimelineEvent.created_at.desc())
                .limit(25)
            )
        )
        .scalars()
        .all()
    )
    docs = (
        (
            await session.execute(
                select(CustomerDocument)
                .where(
                    CustomerDocument.customer_id == customer.id,
                    CustomerDocument.tenant_id == tenant_id,
                )
                .order_by(CustomerDocument.document_type.asc())
            )
        )
        .scalars()
        .all()
    )
    conv_ids = [r.id for r in convs_rows]
    messages: list[MessageRow] = []
    if conv_ids:
        messages = (
            (
                await session.execute(
                    select(MessageRow)
                    .where(
                        MessageRow.conversation_id.in_(conv_ids), MessageRow.tenant_id == tenant_id
                    )
                    .order_by(MessageRow.sent_at.desc())
                    .limit(8)
                )
            )
            .scalars()
            .all()
        )
    ai_items = (
        (
            await session.execute(
                select(CustomerAIReviewItem)
                .where(
                    CustomerAIReviewItem.customer_id == customer.id,
                    CustomerAIReviewItem.tenant_id == tenant_id,
                )
                .order_by(CustomerAIReviewItem.created_at.desc())
                .limit(10)
            )
        )
        .scalars()
        .all()
    )
    last_extracted = (convs_rows[0].extracted_data or {}) if convs_rows else {}
    total_cost = sum((r.total_cost_usd or Decimal("0") for r in convs_rows), start=Decimal("0"))
    return CustomerDetail(
        **list_item.model_dump(),
        attrs=customer.attrs or {},
        conversations=conversations,
        last_extracted_data=last_extracted,
        total_cost_usd=total_cost,
        latest_score=_score_out(latest_score) if latest_score else None,
        open_risks=[_risk_out(r) for r in risks],
        next_best_actions=[_action_out(a) for a in actions],
        timeline=[_timeline_out(t) for t in timeline],
        documents=[_document_out(d) for d in docs],
        messages=[_message_out(m) for m in messages],
        ai_review_items=[_ai_review_out(i) for i in ai_items],
    )


async def _ensure_default_documents(session: AsyncSession, customer: Customer) -> None:
    existing = (
        (
            await session.execute(
                select(CustomerDocument.document_type).where(
                    CustomerDocument.customer_id == customer.id,
                    CustomerDocument.tenant_id == customer.tenant_id,
                )
            )
        )
        .scalars()
        .all()
    )
    existing_set = set(existing)
    for doc_type, label in DOCUMENT_TYPES:
        if doc_type not in existing_set:
            session.add(
                CustomerDocument(
                    tenant_id=customer.tenant_id,
                    customer_id=customer.id,
                    document_type=doc_type,
                    label=label,
                    status="missing",
                )
            )


async def _backfill_existing_customer_ops(
    session: AsyncSession, tenant_id: UUID, user: AuthUser
) -> bool:
    changed = False
    customers = (
        (
            await session.execute(
                select(Customer)
                .where(Customer.tenant_id == tenant_id)
                .order_by(Customer.created_at.desc())
                .limit(120)
            )
        )
        .scalars()
        .all()
    )
    for customer in customers:
        docs_count = (
            await session.execute(
                select(func.count())
                .select_from(CustomerDocument)
                .where(
                    CustomerDocument.customer_id == customer.id,
                    CustomerDocument.tenant_id == tenant_id,
                )
            )
        ).scalar_one()
        action_count = (
            await session.execute(
                select(func.count())
                .select_from(CustomerNextBestAction)
                .where(
                    CustomerNextBestAction.customer_id == customer.id,
                    CustomerNextBestAction.tenant_id == tenant_id,
                    CustomerNextBestAction.status == "active",
                )
            )
        ).scalar_one()
        if docs_count == 0:
            await _ensure_default_documents(session, customer)
            changed = True
        if not customer.ai_summary:
            customer.ai_summary = "Cliente con contexto operativo listo para seguimiento."
            customer.ai_confidence = customer.ai_confidence or 0.74
            changed = True
        if customer.last_activity_at is None:
            customer.last_activity_at = customer.created_at
            changed = True
        if action_count == 0 or docs_count == 0:
            await _sync_customer_ops(session, customer, actor_user_id=user.user_id)
            changed = True
    return changed


async def _ensure_demo_data(session: AsyncSession, tenant_id: UUID, user: AuthUser) -> None:  # noqa: ARG002
    # Gate on tenant.is_demo, not on email — email is fragile.
    _result = await session.execute(_sa_select(_Tenant).where(_Tenant.id == tenant_id))
    _tenant = _result.scalar_one_or_none()
    if not _tenant or not _tenant.is_demo:
        return
    backfilled = await _backfill_existing_customer_ops(session, tenant_id, user)
    existing_demo = (
        await session.execute(
            select(func.count())
            .select_from(Customer)
            .where(Customer.tenant_id == tenant_id, Customer.source == "AtendIA Demo CRM")
        )
    ).scalar_one()
    if existing_demo >= 50:
        if backfilled:
            await session.commit()
        return

    users = (
        await session.execute(
            select(TenantUser.id, TenantUser.email)
            .where(TenantUser.tenant_id == tenant_id)
            .order_by(TenantUser.created_at.asc())
        )
    ).all()
    user_ids = [u.id for u in users] or [user.user_id]
    names = [
        "Mariana Perez",
        "Diego Lopez",
        "Karla Mendez",
        "Jose Hernandez",
        "Sofia Aguilar",
        "Ricardo Cruz",
        "Andrea Pineda",
        "Luis Gonzalez",
        "Valeria Flores",
        "Eduardo Medina",
        "Natalia Rios",
        "Carlos Ramirez",
        "Fernanda Ruiz",
        "Oscar Salinas",
        "Patricia Vega",
        "Miguel Torres",
        "Daniela Castillo",
        "Roberto Ibarra",
        "Claudia Pena",
        "Ivan Contreras",
        "Paola Sanchez",
        "Hector Navarro",
        "Alicia Ortega",
        "Samuel Moreno",
        "Gabriel Soto",
        "Monica Juarez",
        "Javier Cardenas",
        "Lorena Acosta",
        "Emilio Vargas",
        "Rosa Molina",
        "Adrian Bautista",
        "Carmen Leon",
        "Felipe Luna",
        "Teresa Cano",
        "Victor Robles",
        "Laura Castillo",
        "Omar Medina",
        "Elena Vazquez",
        "Pedro Vega",
        "Ana Gomez",
        "Juan Perez",
        "Maria Lopez",
        "Carlos Ruiz",
        "Ana Diaz",
        "Luis Martinez",
        "Noemi Herrera",
        "Ernesto Prieto",
        "Gloria Franco",
        "Raul Escobar",
        "Silvia Nunez",
    ]
    stages = list(CLIENT_STAGES.keys())
    now = _now()
    for i, name in enumerate(names):
        phone = f"+5255100{i:05d}"
        existing = (
            await session.execute(
                select(Customer).where(
                    Customer.tenant_id == tenant_id, Customer.phone_e164 == phone
                )
            )
        ).scalar_one_or_none()
        if existing:
            continue
        stage = stages[i % len(stages)]
        idle_hours = [1, 3, 9, 11, 12, 13, 2, 24, 5, 14, 0.5, 26][i % 12]
        assigned = (
            None
            if i % 5 == 0 or stage == "negotiation" and i % 3 == 0
            else user_ids[i % len(user_ids)]
        )
        confidence = 0.52 if i % 13 == 0 else 0.82 + (i % 12) / 100
        customer = Customer(
            tenant_id=tenant_id,
            phone_e164=phone,
            name=name,
            email=f"{name.split()[0].lower()}.{name.split()[-1].lower()}@example.com"
            if i % 4
            else None,
            source="AtendIA Demo CRM",
            tags=["credito", "whatsapp"] + (["alto-potencial"] if i % 4 == 0 else []),
            stage=stage,
            status="active" if "closed" not in stage else "inactive",
            assigned_user_id=assigned,
            last_activity_at=now - timedelta(hours=idle_hours),
            attrs={
                "intent_score": 92 - (i % 7) * 6,
                "engagement_score": 88 - (i % 5) * 8,
                "credit_type": "nomina" if i % 2 == 0 else "contado",
                "budget": 180000 + i * 7500,
                "vehicle_interest": ["Jetta 2024", "T-Cross 2024", "Virtus 2024", "Tiguan R-Line"][
                    i % 4
                ],
                "city": ["Monterrey", "CDMX", "Guadalajara", "Queretaro"][i % 4],
                "objections": ["tasa de interes", "tiempo de aprobacion"] if i % 6 == 0 else [],
            },
            ai_summary="Cliente con senales de compra y avance operativo pendiente.",
            ai_confidence=confidence,
            last_ai_action_at=now - timedelta(hours=idle_hours + 0.4),
            last_human_action_at=None
            if i % 4 == 0
            else now - timedelta(hours=max(1, idle_hours - 1)),
        )
        session.add(customer)
        await session.flush()
        conv = Conversation(
            tenant_id=tenant_id,
            customer_id=customer.id,
            channel="whatsapp_meta",
            status="active",
            current_stage=stage,
            assigned_user_id=assigned,
            last_activity_at=customer.last_activity_at,
            unread_count=1 if i % 6 == 0 else 0,
            tags=customer.tags,
        )
        session.add(conv)
        await session.flush()
        session.add(
            ConversationStateRow(
                conversation_id=conv.id,
                extracted_data=customer.attrs,
                last_intent="comprar_auto" if i % 2 == 0 else "resolver_duda",
                total_cost_usd=Decimal("0.0142"),
            )
        )
        session.add_all(
            [
                MessageRow(
                    tenant_id=tenant_id,
                    conversation_id=conv.id,
                    direction="inbound",
                    text="Cuanto tarda la aprobacion?",
                    metadata_json={"sender_type": "client", "intent_detected": "credit_question"},
                    sent_at=customer.last_activity_at or now,
                ),
                MessageRow(
                    tenant_id=tenant_id,
                    conversation_id=conv.id,
                    direction="outbound",
                    text="Generalmente 24-48h con documentos completos.",
                    metadata_json={
                        "sender_type": "ai",
                        "confidence_score": confidence,
                        "related_workflow": "credit_followup",
                    },
                    sent_at=(customer.last_activity_at or now) + timedelta(minutes=2),
                ),
            ]
        )
        for j, (doc_type, label) in enumerate(DOCUMENT_TYPES):
            received = j < (i % 5)
            session.add(
                CustomerDocument(
                    tenant_id=tenant_id,
                    customer_id=customer.id,
                    document_type=doc_type,
                    label=label,
                    status="approved"
                    if received and j % 2 == 0
                    else "received"
                    if received
                    else "missing",
                    uploaded_at=now - timedelta(hours=idle_hours - 0.2) if received else None,
                )
            )
        session.add_all(
            [
                CustomerTimelineEvent(
                    tenant_id=tenant_id,
                    customer_id=customer.id,
                    event_type="lead_created",
                    title="Lead creado",
                    description="Origen: AtendIA Demo CRM",
                    actor_type="system",
                    created_at=now - timedelta(days=2, hours=i % 9),
                ),
                CustomerTimelineEvent(
                    tenant_id=tenant_id,
                    customer_id=customer.id,
                    event_type="message_received",
                    title="Cliente respondio WhatsApp",
                    description="Pregunta sobre aprobacion y requisitos.",
                    actor_type="human",
                    actor_id=assigned,
                    created_at=customer.last_activity_at or now,
                ),
            ]
        )
        await _sync_customer_ops(session, customer, actor_user_id=user.user_id)
        if confidence < 0.62 or i % 11 == 0:
            session.add(
                CustomerAIReviewItem(
                    tenant_id=tenant_id,
                    customer_id=customer.id,
                    conversation_id=conv.id,
                    issue_type="low_confidence_response",
                    severity="high" if confidence < 0.6 else "medium",
                    title="Respuesta IA requiere revision",
                    description="Confianza baja o posible brecha de conocimiento detectada.",
                    ai_summary=customer.ai_summary,
                    confidence=confidence,
                    risky_output_flag=confidence < 0.55,
                )
            )
    await session.commit()


@router.get("", response_model=CustomerListResponse)
async def list_customers(
    user: AuthUser = Depends(current_user),
    tenant_id: UUID = Depends(current_tenant_id),
    q: str | None = Query(None, description="phone, email or name substring"),
    stage: str | None = Query(None),
    assigned_user_id: UUID | None = Query(None),
    risk_level: str | None = Query(None),
    sla_status: str | None = Query(None),
    sort_by: str = Query("created_at", pattern="^(name|last_activity|score|created_at|risk|sla)$"),
    sort_dir: str = Query("desc", pattern="^(asc|desc)$"),
    limit: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_db_session),
) -> CustomerListResponse:
    await _ensure_demo_data(session, tenant_id, user)
    items = await _customer_list_base(
        session,
        tenant_id,
        q=q,
        stage=stage,
        assigned_user_id=assigned_user_id,
        risk_level=risk_level,
        sla_status=sla_status,
        sort_by=sort_by,
        sort_dir=sort_dir,
        limit=limit,
    )
    return CustomerListResponse(items=items)


@router.post("", response_model=CustomerDetail, status_code=status.HTTP_201_CREATED)
async def create_customer(
    body: CustomerCreate,
    user: AuthUser = Depends(current_user),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> CustomerDetail:
    phone = _normalize_phone(body.phone_e164)
    if not phone:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid phone")
    existing = (
        await session.execute(
            select(Customer).where(Customer.tenant_id == tenant_id, Customer.phone_e164 == phone)
        )
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status.HTTP_409_CONFLICT, "customer already exists")
    customer = Customer(
        tenant_id=tenant_id,
        phone_e164=phone,
        name=body.name,
        email=body.email,
        source=body.source,
        tags=body.tags,
        stage=body.stage,
        attrs=body.attrs,
        last_activity_at=_now(),
    )
    session.add(customer)
    await session.flush()
    await _ensure_default_documents(session, customer)
    session.add(
        CustomerTimelineEvent(
            tenant_id=tenant_id,
            customer_id=customer.id,
            event_type="lead_created",
            title="Cliente creado",
            description="Alta manual desde Command Center.",
            actor_type="human",
            actor_id=user.user_id,
        )
    )
    await _sync_customer_ops(session, customer, actor_user_id=user.user_id)
    await emit_admin_event(
        session,
        tenant_id=tenant_id,
        actor_user_id=user.user_id,
        action="customer.created",
        payload={"customer_id": str(customer.id), "phone": phone},
    )
    await session.commit()
    await session.refresh(customer)
    return await _detail_payload(customer, tenant_id, session)


@router.get("/{customer_id:uuid}", response_model=CustomerDetail)
async def get_customer(
    customer_id: UUID,
    user: AuthUser = Depends(current_user),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> CustomerDetail:
    await _ensure_demo_data(session, tenant_id, user)
    customer = await _verify_customer(customer_id, tenant_id, session)
    return await _detail_payload(customer, tenant_id, session)


@router.patch("/{customer_id:uuid}", response_model=CustomerDetail)
async def patch_customer(
    customer_id: UUID,
    body: CustomerPatch,
    user: AuthUser = Depends(current_user),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> CustomerDetail:
    customer = await _verify_customer(customer_id, tenant_id, session)
    changes = body.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "no fields to update")

    previous = {k: getattr(customer, k) for k in changes}
    for k, v in changes.items():
        setattr(customer, k, v)
    customer.sla_status = _sla_status(
        customer.stage, customer.last_activity_at, customer.created_at, _now()
    )
    await _sync_customer_ops(session, customer, actor_user_id=user.user_id)
    session.add(
        CustomerTimelineEvent(
            tenant_id=tenant_id,
            customer_id=customer.id,
            event_type="field_changed",
            title="Ficha actualizada",
            description=", ".join(changes.keys()),
            actor_type="human",
            actor_id=user.user_id,
            metadata_json={
                "previous": {k: str(v) for k, v in previous.items()},
                "new": {k: str(v) for k, v in changes.items()},
            },
        )
    )
    await emit_admin_event(
        session,
        tenant_id=tenant_id,
        actor_user_id=user.user_id,
        action="customer.updated",
        payload={"customer_id": str(customer.id), "fields": list(changes.keys())},
    )
    await session.commit()
    await session.refresh(customer)
    return await _detail_payload(customer, tenant_id, session)


@router.delete("/{customer_id:uuid}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_customer(
    customer_id: UUID,
    user: AuthUser = Depends(current_user),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> None:
    result = await session.execute(
        delete(Customer).where(Customer.id == customer_id, Customer.tenant_id == tenant_id)
    )
    if result.rowcount == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "customer not found")
    await emit_admin_event(
        session,
        tenant_id=tenant_id,
        actor_user_id=user.user_id,
        action="customer.deleted",
        payload={"customer_id": str(customer_id)},
    )
    await session.commit()


@router.patch("/{customer_id:uuid}/score", response_model=CustomerDetail)
async def patch_customer_score(
    customer_id: UUID,
    body: ScorePatch,
    user: AuthUser = Depends(current_user),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> CustomerDetail:
    customer = await _verify_customer(customer_id, tenant_id, session)
    customer.score = body.score
    customer.health_score = body.score
    session.add(
        CustomerTimelineEvent(
            tenant_id=tenant_id,
            customer_id=customer.id,
            event_type="score_overridden",
            title="Score editado manualmente",
            description=f"Nuevo score: {body.score}",
            actor_type="human",
            actor_id=user.user_id,
        )
    )
    await session.commit()
    await session.refresh(customer)
    return await _detail_payload(customer, tenant_id, session)


@router.post("/{customer_id:uuid}/assign", response_model=CustomerDetail)
async def assign_customer(
    customer_id: UUID,
    body: AssignBody,
    user: AuthUser = Depends(current_user),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> CustomerDetail:
    customer = await _verify_customer(customer_id, tenant_id, session)
    if body.assigned_user_id:
        exists = (
            await session.execute(
                select(TenantUser.id).where(
                    TenantUser.id == body.assigned_user_id, TenantUser.tenant_id == tenant_id
                )
            )
        ).scalar_one_or_none()
        if not exists:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found")
    customer.assigned_user_id = body.assigned_user_id
    conv = await _latest_conversation(customer_id, tenant_id, session)
    if conv:
        conv.assigned_user_id = body.assigned_user_id
    session.add(
        CustomerTimelineEvent(
            tenant_id=tenant_id,
            customer_id=customer.id,
            event_type="client_assigned",
            title="Cliente asignado",
            description=str(body.assigned_user_id) if body.assigned_user_id else "Sin asignacion",
            actor_type="human",
            actor_id=user.user_id,
        )
    )
    await _sync_customer_ops(session, customer, actor_user_id=user.user_id)
    await session.commit()
    await session.refresh(customer)
    return await _detail_payload(customer, tenant_id, session)


@router.post("/{customer_id:uuid}/change-stage", response_model=CustomerDetail)
async def change_customer_stage(
    customer_id: UUID,
    body: ChangeStageBody,
    user: AuthUser = Depends(current_user),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> CustomerDetail:
    customer = await _verify_customer(customer_id, tenant_id, session)
    previous = customer.stage
    customer.stage = body.stage
    conv = await _latest_conversation(customer_id, tenant_id, session)
    if conv:
        conv.current_stage = body.stage
    session.add(
        CustomerTimelineEvent(
            tenant_id=tenant_id,
            customer_id=customer.id,
            event_type="stage_changed",
            title="Etapa actualizada",
            description=f"{previous} -> {body.stage}",
            actor_type="human",
            actor_id=user.user_id,
            metadata_json={"previous": previous, "new": body.stage},
        )
    )
    await _sync_customer_ops(session, customer, actor_user_id=user.user_id)
    await session.commit()
    await session.refresh(customer)
    return await _detail_payload(customer, tenant_id, session)


@router.post("/{customer_id:uuid}/recalculate-score", response_model=CustomerScoreOut)
async def recalculate_customer_score(
    customer_id: UUID,
    user: AuthUser = Depends(current_user),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> CustomerScoreOut:
    customer = await _verify_customer(customer_id, tenant_id, session)
    score = await _sync_customer_ops(session, customer, actor_user_id=user.user_id)
    await session.commit()
    await session.refresh(score)
    return _score_out(score)


@router.get("/{customer_id:uuid}/score", response_model=CustomerScoreOut | None)
async def get_customer_score(
    customer_id: UUID,
    user: AuthUser = Depends(current_user),  # noqa: ARG001
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> CustomerScoreOut | None:
    await _verify_customer(customer_id, tenant_id, session)
    score = (
        await session.execute(
            select(CustomerScore)
            .where(CustomerScore.customer_id == customer_id, CustomerScore.tenant_id == tenant_id)
            .order_by(CustomerScore.calculated_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return _score_out(score) if score else None


@router.get("/{customer_id:uuid}/risks", response_model=list[CustomerRiskOut])
async def get_customer_risks(
    customer_id: UUID,
    user: AuthUser = Depends(current_user),  # noqa: ARG001
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> list[CustomerRiskOut]:
    await _verify_customer(customer_id, tenant_id, session)
    rows = (
        (
            await session.execute(
                select(CustomerRisk)
                .where(CustomerRisk.customer_id == customer_id, CustomerRisk.tenant_id == tenant_id)
                .order_by(CustomerRisk.status.asc(), CustomerRisk.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return [_risk_out(r) for r in rows]


@router.get("/{customer_id:uuid}/next-best-action", response_model=list[NextBestActionOut])
async def get_next_best_action(
    customer_id: UUID,
    user: AuthUser = Depends(current_user),  # noqa: ARG001
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> list[NextBestActionOut]:
    await _verify_customer(customer_id, tenant_id, session)
    rows = (
        (
            await session.execute(
                select(CustomerNextBestAction)
                .where(
                    CustomerNextBestAction.customer_id == customer_id,
                    CustomerNextBestAction.tenant_id == tenant_id,
                    CustomerNextBestAction.status == "active",
                )
                .order_by(CustomerNextBestAction.priority.desc())
            )
        )
        .scalars()
        .all()
    )
    return [_action_out(r) for r in rows]


@router.post("/{customer_id:uuid}/actions/{action_id:uuid}/execute", response_model=CustomerDetail)
async def execute_next_best_action(
    customer_id: UUID,
    action_id: UUID,
    user: AuthUser = Depends(current_user),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> CustomerDetail:
    customer = await _verify_customer(customer_id, tenant_id, session)
    action = (
        await session.execute(
            select(CustomerNextBestAction).where(
                CustomerNextBestAction.id == action_id,
                CustomerNextBestAction.customer_id == customer_id,
                CustomerNextBestAction.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if action is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "action not found")
    action.status = "executed"
    action.executed_at = _now()
    customer.last_human_action_at = action.executed_at
    session.add(
        CustomerTimelineEvent(
            tenant_id=tenant_id,
            customer_id=customer.id,
            event_type="human_follow_up",
            title=ACTION_LABELS.get(action.action_type, action.action_type),
            description=action.reason,
            actor_type="human",
            actor_id=user.user_id,
            metadata_json={"action_id": str(action.id), "action_type": action.action_type},
        )
    )
    await _sync_customer_ops(session, customer, actor_user_id=user.user_id)
    await session.commit()
    await session.refresh(customer)
    return await _detail_payload(customer, tenant_id, session)


@router.get("/{customer_id:uuid}/timeline", response_model=list[TimelineEventOut])
async def get_customer_timeline(
    customer_id: UUID,
    user: AuthUser = Depends(current_user),  # noqa: ARG001
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> list[TimelineEventOut]:
    await _verify_customer(customer_id, tenant_id, session)
    rows = (
        (
            await session.execute(
                select(CustomerTimelineEvent)
                .where(
                    CustomerTimelineEvent.customer_id == customer_id,
                    CustomerTimelineEvent.tenant_id == tenant_id,
                )
                .order_by(CustomerTimelineEvent.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return [_timeline_out(r) for r in rows]


@router.post(
    "/{customer_id:uuid}/timeline",
    response_model=TimelineEventOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_customer_timeline_event(
    customer_id: UUID,
    body: TimelineCreate,
    user: AuthUser = Depends(current_user),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> TimelineEventOut:
    await _verify_customer(customer_id, tenant_id, session)
    row = CustomerTimelineEvent(
        tenant_id=tenant_id,
        customer_id=customer_id,
        event_type=body.event_type,
        title=body.title,
        description=body.description,
        actor_type=body.actor_type,
        actor_id=user.user_id,
        metadata_json=body.metadata_json,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return _timeline_out(row)


@router.get("/{customer_id:uuid}/documents", response_model=list[CustomerDocumentOut])
async def list_customer_documents(
    customer_id: UUID,
    user: AuthUser = Depends(current_user),  # noqa: ARG001
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> list[CustomerDocumentOut]:
    customer = await _verify_customer(customer_id, tenant_id, session)
    await _ensure_default_documents(session, customer)
    await session.commit()
    rows = (
        (
            await session.execute(
                select(CustomerDocument)
                .where(
                    CustomerDocument.customer_id == customer_id,
                    CustomerDocument.tenant_id == tenant_id,
                )
                .order_by(CustomerDocument.document_type.asc())
            )
        )
        .scalars()
        .all()
    )
    return [_document_out(r) for r in rows]


@router.post(
    "/{customer_id:uuid}/documents",
    response_model=CustomerDocumentOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_customer_document(
    customer_id: UUID,
    body: DocumentCreate,
    user: AuthUser = Depends(current_user),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> CustomerDocumentOut:
    customer = await _verify_customer(customer_id, tenant_id, session)
    now = _now()
    doc = CustomerDocument(
        tenant_id=tenant_id,
        customer_id=customer_id,
        document_type=body.document_type,
        label=body.label or body.document_type,
        status=body.status,
        file_url=body.file_url,
        uploaded_at=now if body.status in {"received", "approved"} else None,
        reviewed_at=now if body.status in {"rejected", "approved"} else None,
        rejection_reason=body.rejection_reason,
    )
    session.add(doc)
    session.add(
        CustomerTimelineEvent(
            tenant_id=tenant_id,
            customer_id=customer_id,
            event_type="documents_uploaded",
            title="Documento actualizado",
            description=doc.label,
            actor_type="human",
            actor_id=user.user_id,
        )
    )
    await _sync_customer_ops(session, customer, actor_user_id=user.user_id)
    await session.commit()
    await session.refresh(doc)
    return _document_out(doc)


@documents_router.patch("/{document_id:uuid}", response_model=CustomerDocumentOut)
async def patch_document(
    document_id: UUID,
    body: DocumentPatch,
    user: AuthUser = Depends(current_user),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> CustomerDocumentOut:
    doc = (
        await session.execute(
            select(CustomerDocument).where(
                CustomerDocument.id == document_id, CustomerDocument.tenant_id == tenant_id
            )
        )
    ).scalar_one_or_none()
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "document not found")
    changes = body.model_dump(exclude_unset=True)
    for k, v in changes.items():
        setattr(doc, k, v)
    if body.status in {"received", "approved"} and doc.uploaded_at is None:
        doc.uploaded_at = _now()
    if body.status in {"approved", "rejected"}:
        doc.reviewed_at = _now()
    customer = await _verify_customer(doc.customer_id, tenant_id, session)
    session.add(
        CustomerTimelineEvent(
            tenant_id=tenant_id,
            customer_id=doc.customer_id,
            event_type="documents_uploaded",
            title="Documento revisado",
            description=f"{doc.label}: {doc.status}",
            actor_type="human",
            actor_id=user.user_id,
        )
    )
    await _sync_customer_ops(session, customer, actor_user_id=user.user_id)
    await session.commit()
    await session.refresh(doc)
    return _document_out(doc)


@router.get("/{customer_id:uuid}/messages", response_model=list[ConversationMessageOut])
async def get_customer_messages(
    customer_id: UUID,
    user: AuthUser = Depends(current_user),  # noqa: ARG001
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> list[ConversationMessageOut]:
    await _verify_customer(customer_id, tenant_id, session)
    convs = (
        (
            await session.execute(
                select(Conversation.id).where(
                    Conversation.customer_id == customer_id, Conversation.tenant_id == tenant_id
                )
            )
        )
        .scalars()
        .all()
    )
    if not convs:
        return []
    rows = (
        (
            await session.execute(
                select(MessageRow)
                .where(MessageRow.conversation_id.in_(convs), MessageRow.tenant_id == tenant_id)
                .order_by(MessageRow.sent_at.desc())
                .limit(50)
            )
        )
        .scalars()
        .all()
    )
    return [_message_out(r) for r in rows]


@router.post(
    "/{customer_id:uuid}/messages",
    response_model=ConversationMessageOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_customer_message(
    customer_id: UUID,
    body: MessageCreate,
    user: AuthUser = Depends(current_user),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> ConversationMessageOut:
    customer = await _verify_customer(customer_id, tenant_id, session)
    conv = await _ensure_conversation(customer, session)
    direction = (
        "inbound"
        if body.sender_type == "client"
        else "outbound"
        if body.sender_type in {"human", "ai"}
        else "system"
    )
    now = _now()
    row = MessageRow(
        tenant_id=tenant_id,
        conversation_id=conv.id,
        direction=direction,
        text=body.body,
        metadata_json={
            "sender_type": body.sender_type,
            "confidence_score": body.confidence_score,
            "intent_detected": body.intent_detected,
            "objection_detected": body.objection_detected,
            "related_workflow": body.related_workflow,
        },
        sent_at=now,
    )
    session.add(row)
    customer.last_activity_at = now
    if body.sender_type == "human":
        customer.last_human_action_at = now
    if body.sender_type == "ai":
        customer.last_ai_action_at = now
        customer.ai_confidence = body.confidence_score
    conv.last_activity_at = now
    session.add(
        CustomerTimelineEvent(
            tenant_id=tenant_id,
            customer_id=customer_id,
            event_type="message_sent" if direction != "inbound" else "message_received",
            title="Mensaje registrado",
            description=body.body[:180],
            actor_type=body.sender_type if body.sender_type in {"ai", "system"} else "human",
            actor_id=user.user_id if body.sender_type == "human" else None,
        )
    )
    await _sync_customer_ops(session, customer, actor_user_id=user.user_id)
    await session.commit()
    await session.refresh(row)
    return _message_out(row)


@router.get("/{customer_id:uuid}/audit")
async def get_customer_audit(
    customer_id: UUID,
    user: AuthUser = Depends(current_user),  # noqa: ARG001
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    await _verify_customer(customer_id, tenant_id, session)
    events = (
        (
            await session.execute(
                select(EventRow)
                .where(
                    EventRow.tenant_id == tenant_id,
                    EventRow.payload["customer_id"].astext == str(customer_id),
                )
                .order_by(EventRow.occurred_at.desc())
                .limit(50)
            )
        )
        .scalars()
        .all()
    )
    timeline = await get_customer_timeline(customer_id, user, tenant_id, session)
    return {
        "events": [
            {
                "id": str(e.id),
                "type": e.type,
                "payload": e.payload,
                "actor_user_id": str(e.actor_user_id) if e.actor_user_id else None,
                "occurred_at": e.occurred_at,
            }
            for e in events
        ],
        "timeline": [t.model_dump(mode="json") for t in timeline],
    }


@dashboard_router.get("/kpis", response_model=CustomerKpis)
async def get_customer_kpis(
    user: AuthUser = Depends(current_user),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> CustomerKpis:
    await _ensure_demo_data(session, tenant_id, user)
    total = (
        await session.execute(
            select(func.count()).select_from(Customer).where(Customer.tenant_id == tenant_id)
        )
    ).scalar_one()
    at_risk = (
        await session.execute(
            select(func.count())
            .select_from(Customer)
            .where(Customer.tenant_id == tenant_id, Customer.risk_level.in_(["high", "critical"]))
        )
    ).scalar_one()
    unassigned = (
        await session.execute(
            select(func.count())
            .select_from(Customer)
            .where(Customer.tenant_id == tenant_id, Customer.assigned_user_id.is_(None))
        )
    ).scalar_one()
    docs_pending = (
        await session.execute(
            select(func.count())
            .select_from(Customer)
            .where(Customer.tenant_id == tenant_id, Customer.documents_status != "complete")
        )
    ).scalar_one()
    negotiations = (
        await session.execute(
            select(func.count())
            .select_from(Customer)
            .where(Customer.tenant_id == tenant_id, Customer.stage == "negotiation")
        )
    ).scalar_one()
    high_without_followup = (
        await session.execute(
            select(func.count())
            .select_from(Customer)
            .where(
                Customer.tenant_id == tenant_id,
                Customer.health_score >= 80,
                or_(
                    Customer.last_human_action_at.is_(None),
                    Customer.last_human_action_at < _now() - timedelta(hours=8),
                ),
            )
        )
    ).scalar_one()
    attention = (
        await session.execute(
            select(func.count())
            .select_from(Customer)
            .where(
                Customer.tenant_id == tenant_id,
                or_(
                    Customer.risk_level.in_(["high", "critical"]), Customer.sla_status == "breached"
                ),
            )
        )
    ).scalar_one()
    ai_open = (
        await session.execute(
            select(func.count())
            .select_from(CustomerAIReviewItem)
            .where(
                CustomerAIReviewItem.tenant_id == tenant_id, CustomerAIReviewItem.status == "open"
            )
        )
    ).scalar_one()
    return CustomerKpis(
        total_clients=total,
        clients_needing_attention=attention,
        high_score_without_followup=high_without_followup,
        at_risk_clients=at_risk,
        unassigned_clients=unassigned,
        documentation_pending=docs_pending,
        active_negotiations=negotiations,
        ai_review_open=ai_open,
    )


@dashboard_router.get("/risk-radar", response_model=RiskRadarResponse)
async def get_risk_radar(
    user: AuthUser = Depends(current_user),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> RiskRadarResponse:
    await _ensure_demo_data(session, tenant_id, user)
    rows = (
        await session.execute(
            select(
                CustomerRisk.risk_type,
                CustomerRisk.severity,
                CustomerRisk.recommended_action,
                CustomerRisk.customer_id,
            )
            .where(CustomerRisk.tenant_id == tenant_id, CustomerRisk.status == "open")
            .order_by(CustomerRisk.created_at.desc())
        )
    ).all()
    grouped: dict[str, dict] = {}
    for r in rows:
        item = grouped.setdefault(
            r.risk_type,
            {
                "title": r.risk_type.replace("_", " ").title(),
                "count": 0,
                "severity": r.severity,
                "affected_client_ids": [],
                "recommended_action": r.recommended_action,
                "action_link": f"/customers?risk={r.risk_type}",
            },
        )
        item["count"] += 1
        item["affected_client_ids"].append(r.customer_id)
        if _risk_rank(r.severity) > _risk_rank(item["severity"]):
            item["severity"] = r.severity
    items = sorted(
        (RadarItem(**v) for v in grouped.values()),
        key=lambda x: (_risk_rank(x.severity), x.count),
        reverse=True,
    )
    return RiskRadarResponse(items=items[:8], updated_at=_now())


@risks_router.get("", response_model=list[CustomerRiskOut])
async def list_risks(
    user: AuthUser = Depends(current_user),  # noqa: ARG001
    tenant_id: UUID = Depends(current_tenant_id),
    status_: str = Query("open", alias="status"),
    session: AsyncSession = Depends(get_db_session),
) -> list[CustomerRiskOut]:
    rows = (
        (
            await session.execute(
                select(CustomerRisk)
                .where(CustomerRisk.tenant_id == tenant_id, CustomerRisk.status == status_)
                .order_by(CustomerRisk.created_at.desc())
                .limit(200)
            )
        )
        .scalars()
        .all()
    )
    return [_risk_out(r) for r in rows]


@risks_router.post("/{risk_id:uuid}/resolve", response_model=CustomerRiskOut)
async def resolve_risk(
    risk_id: UUID,
    user: AuthUser = Depends(current_user),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> CustomerRiskOut:
    row = (
        await session.execute(
            select(CustomerRisk).where(
                CustomerRisk.id == risk_id, CustomerRisk.tenant_id == tenant_id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "risk not found")
    row.status = "resolved"
    row.resolved_at = _now()
    session.add(
        CustomerTimelineEvent(
            tenant_id=tenant_id,
            customer_id=row.customer_id,
            event_type="risk_resolved",
            title="Riesgo resuelto",
            description=row.risk_type,
            actor_type="human",
            actor_id=user.user_id,
        )
    )
    await session.commit()
    await session.refresh(row)
    return _risk_out(row)


@ai_review_router.get("", response_model=AIReviewQueueResponse)
async def get_ai_review_queue(
    user: AuthUser = Depends(current_user),  # noqa: ARG001
    tenant_id: UUID = Depends(current_tenant_id),
    status_: str = Query("open", alias="status"),
    session: AsyncSession = Depends(get_db_session),
) -> AIReviewQueueResponse:
    rows = (
        (
            await session.execute(
                select(CustomerAIReviewItem)
                .where(
                    CustomerAIReviewItem.tenant_id == tenant_id,
                    CustomerAIReviewItem.status == status_,
                )
                .order_by(CustomerAIReviewItem.created_at.desc())
                .limit(100)
            )
        )
        .scalars()
        .all()
    )
    return AIReviewQueueResponse(items=[_ai_review_out(r) for r in rows])


@ai_review_router.post("/{item_id:uuid}/resolve", response_model=AIReviewItemOut)
async def resolve_ai_review_item(
    item_id: UUID,
    user: AuthUser = Depends(current_user),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> AIReviewItemOut:
    row = (
        await session.execute(
            select(CustomerAIReviewItem).where(
                CustomerAIReviewItem.id == item_id, CustomerAIReviewItem.tenant_id == tenant_id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "review item not found")
    row.status = "resolved"
    row.resolved_at = _now()
    row.feedback_status = row.feedback_status or "reviewed"
    session.add(
        CustomerTimelineEvent(
            tenant_id=tenant_id,
            customer_id=row.customer_id,
            event_type="ai_review_resolved",
            title="Revision IA resuelta",
            description=row.title,
            actor_type="human",
            actor_id=user.user_id,
        )
    )
    await session.commit()
    await session.refresh(row)
    return _ai_review_out(row)


@ai_review_router.post("/{item_id:uuid}/feedback", response_model=AIReviewItemOut)
async def feedback_ai_review_item(
    item_id: UUID,
    body: dict,
    user: AuthUser = Depends(current_user),  # noqa: ARG001
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> AIReviewItemOut:
    row = (
        await session.execute(
            select(CustomerAIReviewItem).where(
                CustomerAIReviewItem.id == item_id, CustomerAIReviewItem.tenant_id == tenant_id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "review item not found")
    row.feedback_status = str(body.get("feedback_status") or body.get("status") or "feedback_sent")
    await session.commit()
    await session.refresh(row)
    return _ai_review_out(row)


CUSTOMER_IMPORT_MAX_ROWS: int = 2000
CUSTOMER_IMPORT_MAX_BYTES: int = 5 * 1024 * 1024


def _read_csv_rows(raw: bytes) -> list[dict[str, str]]:
    text_data = raw.decode("utf-8-sig", errors="ignore")
    reader = csv.DictReader(io.StringIO(text_data))
    rows = list(reader)
    if len(rows) > CUSTOMER_IMPORT_MAX_ROWS:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"too many rows (max {CUSTOMER_IMPORT_MAX_ROWS})",
        )
    return rows


def _parse_import_row(
    idx: int, row: dict[str, str], seen_phones: set[str]
) -> tuple[dict | None, str | None]:
    phone = _normalize_phone(row.get("phone") or row.get("phone_e164") or row.get("telefono") or "")
    if not phone:
        return None, f"row {idx}: invalid phone"
    if phone in seen_phones:
        return None, f"row {idx}: duplicate phone in file"
    name = (row.get("name") or row.get("nombre") or "").strip() or None
    email, email_err = _validate_email(row.get("email") or row.get("correo"))
    if email_err:
        return None, f"row {idx}: {email_err}"
    score, score_err = _validate_score(row.get("score") or row.get("puntaje"))
    if score_err:
        return None, f"row {idx}: {score_err}"
    return {"phone": phone, "name": name, "email": email, "score": score}, None


@router.post("/import/preview", response_model=CustomerImportPreview)
async def preview_import(
    file: UploadFile = File(...),
    user: AuthUser = Depends(current_user),  # noqa: ARG001
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> CustomerImportPreview:
    raw = await file.read()
    if len(raw) > CUSTOMER_IMPORT_MAX_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"file too large (max {CUSTOMER_IMPORT_MAX_BYTES // 1024 // 1024} MB)",
        )
    rows = _read_csv_rows(raw)
    valid: list[CustomerImportPreviewRow] = []
    errors: list[str] = []
    seen: set[str] = set()
    for idx, row in enumerate(rows, start=2):
        parsed, err = _parse_import_row(idx, row, seen)
        if err:
            errors.append(err)
            continue
        assert parsed is not None
        seen.add(parsed["phone"])
        existing = (
            await session.execute(
                select(Customer.id).where(
                    Customer.tenant_id == tenant_id, Customer.phone_e164 == parsed["phone"]
                )
            )
        ).scalar_one_or_none()
        valid.append(
            CustomerImportPreviewRow(
                row=idx,
                phone=parsed["phone"],
                name=parsed["name"],
                email=parsed["email"],
                score=parsed["score"],
                will="update" if existing else "create",
            )
        )
    return CustomerImportPreview(valid_rows=valid, errors=errors, total=len(rows))


@router.post("/import", response_model=CustomerImportResult)
async def import_customers(
    file: UploadFile = File(...),
    user: AuthUser = Depends(current_user),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> CustomerImportResult:
    raw = await file.read()
    if len(raw) > CUSTOMER_IMPORT_MAX_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"file too large (max {CUSTOMER_IMPORT_MAX_BYTES // 1024 // 1024} MB)",
        )
    rows = _read_csv_rows(raw)
    created = 0
    updated = 0
    errors: list[str] = []
    seen: set[str] = set()
    for idx, row in enumerate(rows, start=2):
        parsed, err = _parse_import_row(idx, row, seen)
        if err:
            errors.append(err)
            continue
        assert parsed is not None
        seen.add(parsed["phone"])
        existing = (
            await session.execute(
                select(Customer).where(
                    Customer.tenant_id == tenant_id, Customer.phone_e164 == parsed["phone"]
                )
            )
        ).scalar_one_or_none()
        if existing:
            if parsed["name"]:
                existing.name = parsed["name"]
            if parsed["email"]:
                existing.email = parsed["email"]
            if parsed["score"] is not None:
                existing.score = parsed["score"]
                existing.health_score = parsed["score"]
            existing.last_activity_at = existing.last_activity_at or _now()
            await _sync_customer_ops(session, existing, actor_user_id=user.user_id)
            if parsed["score"] is not None:
                existing.score = parsed["score"]
                existing.health_score = parsed["score"]
            updated += 1
        else:
            customer = Customer(
                tenant_id=tenant_id,
                phone_e164=parsed["phone"],
                name=parsed["name"],
                email=parsed["email"],
                score=parsed["score"] or 0,
                health_score=parsed["score"] or 0,
                source="CSV",
                last_activity_at=_now(),
            )
            session.add(customer)
            await session.flush()
            await _ensure_default_documents(session, customer)
            await _sync_customer_ops(session, customer, actor_user_id=user.user_id)
            if parsed["score"] is not None:
                customer.score = parsed["score"]
                customer.health_score = parsed["score"]
            created += 1
    await session.commit()
    return CustomerImportResult(created=created, updated=updated, errors=errors)


@router.get("/export")
async def export_customers(
    user: AuthUser = Depends(current_user),  # noqa: ARG001
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    rows = await _customer_list_base(
        session, tenant_id, sort_by="created_at", sort_dir="desc", limit=5000
    )
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(
        ["name", "phone", "email", "stage", "score", "risk_level", "sla_status", "last_activity"]
    )
    for row in rows:
        writer.writerow(
            [
                _csv_safe(row.name or ""),
                _csv_safe(row.phone_e164),
                _csv_safe(row.email or ""),
                _csv_safe(row.effective_stage or row.stage or ""),
                row.score or 0,
                row.risk_level,
                row.sla_status,
                row.last_activity_at.isoformat() if row.last_activity_at else "",
            ]
        )
    return Response(
        content=out.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="customers.csv"'},
    )


def _normalize_phone(raw: str) -> str | None:
    if not raw:
        return None
    has_plus = "+" in raw
    digits = "".join(ch for ch in raw if ch.isdigit())
    if not digits:
        return None

    if has_plus:
        if len(digits) == 13 and digits.startswith("521"):
            return f"+52{digits[3:]}"
        if 11 <= len(digits) <= 15:
            return f"+{digits}"
        return None

    if len(digits) == 10:
        return f"+52{digits}"
    if len(digits) == 11 and digits.startswith("1"):
        return f"+52{digits[1:]}"
    if len(digits) == 12 and digits.startswith("52"):
        return f"+{digits}"
    if len(digits) == 13 and digits.startswith("521"):
        return f"+52{digits[3:]}"
    if 11 <= len(digits) <= 15:
        return f"+{digits}"
    return None


def _csv_safe(value: str) -> str:
    if not value:
        return value
    if value[0] in ("=", "+", "-", "@", "\t", "\r"):
        return f"'{value}"
    return value


def _validate_score(raw: object) -> tuple[int | None, str | None]:
    if raw is None or raw == "":
        return None, None
    try:
        n = int(str(raw).strip())
    except (ValueError, TypeError):
        return None, "score must be an integer 0-100"
    if n < 0 or n > 100:
        return None, "score must be between 0 and 100"
    return n, None


def _validate_email(raw: object) -> tuple[str | None, str | None]:
    if raw is None or raw == "":
        return None, None
    cleaned = str(raw).strip()
    if not cleaned:
        return None, None
    if "@" not in cleaned or len(cleaned) > 160:
        return None, "email looks invalid"
    return cleaned, None
