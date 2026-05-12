# ruff: noqa: E501, I001, RUF005
"""AtendIA Handoff Command Center API.

The legacy /handoffs route remains a small operational queue. This sub-router
adds the command-center surface: SLA/priority scoring, smart assignment,
AI explanation, draft generation, feedback and analytics-ready payloads.

Rows from ``human_handoffs`` are enriched when present. For local development
and sparse demo tenants, deterministic seeded cases are appended so the UI is
useful immediately without external services.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal
from uuid import UUID, NAMESPACE_URL, uuid5

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from redis.asyncio import Redis
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from atendia._demo.fixtures import DEMO_HUMAN_AGENTS
from atendia.api._auth_helpers import AuthUser
from atendia.api._deps import current_tenant_id, current_user
from atendia.config import get_settings
from atendia.db.models.conversation import Conversation
from atendia.db.models.customer import Customer
from atendia.db.models.lifecycle import HumanHandoff
from atendia.db.models.tenant import Tenant, TenantUser
from atendia.db.session import get_db_session
from atendia.realtime.publisher import publish_event

router = APIRouter(prefix="/command-center")

AuthedUser = Annotated[AuthUser, Depends(current_user)]
TenantId = Annotated[UUID, Depends(current_tenant_id)]
DbSession = Annotated[AsyncSession, Depends(get_db_session)]

Urgency = Literal["critical", "high", "medium", "low"]
SlaStatus = Literal["healthy", "warning", "breached"]
Sentiment = Literal["positive", "neutral", "negative"]
HandoffStatus = Literal["open", "assigned", "resolved", "escalated"]
FeedbackType = Literal[
    "correct_escalation",
    "ai_should_have_answered",
    "knowledge_gap",
    "routing_issue",
    "wrong_answer",
    "policy_risk_avoided",
]

SLA_MINUTES: dict[Urgency, int] = {
    "critical": 5,
    "high": 15,
    "medium": 30,
    "low": 60,
}

AI_AGENTS = [
    {"id": "ventas-pro", "name": "Ventas Pro", "purpose": "Ventas y cotizacion", "confidence_avg": 0.73, "total_escalations": 28},
    {"id": "credito-ia", "name": "Credito IA", "purpose": "Credito y documentos", "confidence_avg": 0.68, "total_escalations": 22},
    {"id": "agenda-bot", "name": "Agenda Bot", "purpose": "Citas y disponibilidad", "confidence_avg": 0.81, "total_escalations": 14},
    {"id": "soporte-pagos", "name": "Soporte Pagos", "purpose": "Pagos y errores", "confidence_avg": 0.66, "total_escalations": 19},
    {"id": "kb-general", "name": "KB General", "purpose": "FAQs y soporte general", "confidence_avg": 0.76, "total_escalations": 17},
]

SEED_HANDOFFS = [
    {"customer": "Maria Fernanda Lopez", "phone": "+52 55 4422 8811", "reason": "Factura fiscal / Datos incorrectos", "message": "Necesito una factura fiscal con mis datos correctos, ya van dos veces que me la mandan mal.", "intent": "facturacion", "confidence": 0.23, "wait": 32, "value": 12580, "stage": "Negociacion", "sentiment": "negative", "agent": None, "suggested": "Andrea Ruiz", "ai_agent": "Ventas Pro", "missing": ["RFC o razon social", "Uso de CFDI"], "rule": "R-INV-03: Solicitud de intervencion humana + errores de datos fiscales"},
    {"customer": "Juan Carlos Ramirez", "phone": "+52 81 2345 6789", "reason": "Negociacion de precio", "message": "¿Pueden igualar el precio de la competencia? Si me respetan eso cierro hoy.", "intent": "descuento", "confidence": 0.45, "wait": 14, "value": 24900, "stage": "Negociacion", "sentiment": "neutral", "agent": "Carlos Mendez", "suggested": "Carlos Mendez", "ai_agent": "Ventas Pro", "missing": ["Autorizacion de descuento"], "rule": "R-SALES-07: Solicitud de descuento fuera de politica automatica"},
    {"customer": "Ana Sofia Herrera", "phone": "+52 33 9988 7766", "reason": "Disponibilidad / Agenda", "message": "¿Tienen disponibilidad para instalar este sabado? Solo puedo ir en la tarde.", "intent": "agenda", "confidence": 0.68, "wait": 9, "value": 8450, "stage": "Calificacion", "sentiment": "positive", "agent": None, "suggested": "Luis Ortega", "ai_agent": "Agenda Bot", "missing": ["Sucursal preferida", "Horario exacto"], "rule": "R-AGENDA-02: Excepcion de horario requiere confirmacion humana"},
    {"customer": "Roberto Fernandez", "phone": "+52 55 6677 8899", "reason": "Error de sistema / Pago", "message": "No pude completar mi pago, me da error 503 y ya me urge apartar la moto.", "intent": "pago_fallido", "confidence": 0.52, "wait": 6, "value": 11290, "stage": "Sistema", "sentiment": "negative", "agent": "Mariana Vega", "suggested": "Mariana Vega", "ai_agent": "Soporte Pagos", "missing": ["Referencia de pago", "Captura del error"], "rule": "R-PAY-01: Error tecnico + frustracion del cliente + reintentos fallidos"},
    {"customer": "Daniela Torres", "phone": "+52 81 9090 1212", "reason": "Documentos incompletos", "message": "Ya subi mi INE pero no tengo comprobante a mi nombre, ¿que hago?", "intent": "documentos_credito", "confidence": 0.31, "wait": 21, "value": 18200, "stage": "Documentos", "sentiment": "neutral", "agent": None, "suggested": "Andrea Ruiz", "ai_agent": "Credito IA", "missing": ["Comprobante de domicilio", "Validacion de titular"], "rule": "R-DOC-04: Documento faltante con excepcion de politica"},
    {"customer": "Hector Molina", "phone": "+52 55 7000 1000", "reason": "Cliente pidio humano", "message": "Pasame con alguien real, el bot no entiende lo de mi enganche.", "intent": "humano", "confidence": 0.38, "wait": 18, "value": 15890, "stage": "Enganche listo", "sentiment": "negative", "agent": None, "suggested": "Paola Nava", "ai_agent": "Credito IA", "missing": ["Monto de enganche", "Plan credito"], "rule": "R-HUM-01: Cliente solicita humano explicitamente"},
    {"customer": "Valeria Cano", "phone": "+52 33 1212 3434", "reason": "Baja confianza IA", "message": "¿Si estoy en buro puedo sacar la Dinamo R1 con nomina en efectivo?", "intent": "credito_buro", "confidence": 0.19, "wait": 26, "value": 21990, "stage": "Calificacion", "sentiment": "neutral", "agent": "Andrea Ruiz", "suggested": "Andrea Ruiz", "ai_agent": "Credito IA", "missing": ["Tipo de ingreso", "Score buro", "Plan credito"], "rule": "R-AI-LOW-02: Confianza menor a 30% en credito"},
    {"customer": "Miguel Angel Prieto", "phone": "+52 81 8080 7070", "reason": "Fuera de horario", "message": "Estoy afuera de la sucursal, ¿si alcanzo a dejar papeles?", "intent": "horario_sucursal", "confidence": 0.63, "wait": 43, "value": 9300, "stage": "Documentos", "sentiment": "negative", "agent": None, "suggested": "Luis Ortega", "ai_agent": "Agenda Bot", "missing": ["Sucursal", "Horario real"], "rule": "R-AH-01: Mensaje fuera de horario con visita presencial"},
    {"customer": "Lucia Martinez", "phone": "+52 55 1001 2002", "reason": "Queja o frustracion", "message": "Llevo tres dias esperando respuesta, si no me ayudan cancelo.", "intent": "queja", "confidence": 0.34, "wait": 52, "value": 26600, "stage": "Cita", "sentiment": "negative", "agent": "Paola Nava", "suggested": "Paola Nava", "ai_agent": "KB General", "missing": ["Historial de promesa", "Responsable anterior"], "rule": "R-SENT-09: Sentimiento negativo + amenaza de cancelacion"},
    {"customer": "Oscar Ibarra", "phone": "+52 33 6000 7000", "reason": "Pregunta no encontrada en KB", "message": "¿Puedo facturar a una empresa de otro estado con entrega en Monterrey?", "intent": "facturacion_foranea", "confidence": 0.28, "wait": 11, "value": 14100, "stage": "Nuevo", "sentiment": "neutral", "agent": None, "suggested": "Diego Salas", "ai_agent": "KB General", "missing": ["Politica fiscal foranea"], "rule": "R-KB-404: No hay respuesta confiable en conocimiento"},
    {"customer": "Nadia Flores", "phone": "+52 81 4545 4545", "reason": "Disponibilidad / Agenda", "message": "Quiero apartar la Dinamo U5 hoy, ¿sigue disponible en negro?", "intent": "stock_color", "confidence": 0.57, "wait": 4, "value": 17800, "stage": "Nuevo", "sentiment": "positive", "agent": None, "suggested": "Luis Ortega", "ai_agent": "Ventas Pro", "missing": ["Stock por color", "Sucursal"], "rule": "R-STOCK-01: No inventar disponibilidad"},
    {"customer": "Rafael Cordero", "phone": "+52 55 9099 8888", "reason": "Documentos incompletos", "message": "Me pagan en efectivo y no tengo nomina, pero si puedo dar enganche.", "intent": "credito_efectivo", "confidence": 0.42, "wait": 39, "value": 20400, "stage": "Documentos", "sentiment": "neutral", "agent": "Andrea Ruiz", "suggested": "Andrea Ruiz", "ai_agent": "Credito IA", "missing": ["Comprobante ingresos", "Enganche confirmado"], "rule": "R-CREDIT-12: Caso de ingreso no estandar"},
    {"customer": "Patricia Salas", "phone": "+52 33 2010 5566", "reason": "Error de sistema / Pago", "message": "Me cobraron dos veces el apartado, necesito solucion hoy.", "intent": "doble_cargo", "confidence": 0.25, "wait": 7, "value": 10990, "stage": "Sistema", "sentiment": "negative", "agent": "Mariana Vega", "suggested": "Paola Nava", "ai_agent": "Soporte Pagos", "missing": ["Referencia bancaria", "Ultimos 4 digitos"], "rule": "R-PAY-CRIT: Doble cargo reportado"},
    {"customer": "Emilio Rivas", "phone": "+52 81 7777 1212", "reason": "Negociacion de precio", "message": "Si me incluyen casco y placas, firmo hoy con transferencia.", "intent": "paquete_cierre", "confidence": 0.49, "wait": 16, "value": 31400, "stage": "Cerrado", "sentiment": "positive", "agent": "Carlos Mendez", "suggested": "Carlos Mendez", "ai_agent": "Ventas Pro", "missing": ["Autorizacion paquete", "Disponibilidad placas"], "rule": "R-CLOSE-04: Condicion comercial para cierre"},
    {"customer": "Gabriela Mejia", "phone": "+52 55 3030 4040", "reason": "Baja confianza IA", "message": "¿Aceptan INE de otro estado y comprobante de mi tia?", "intent": "ine_comprobante", "confidence": 0.22, "wait": 28, "value": 18700, "stage": "Documentos", "sentiment": "neutral", "agent": None, "suggested": "Diego Salas", "ai_agent": "Credito IA", "missing": ["Regla INE foranea", "Comprobante tercero"], "rule": "R-AI-LOW-02 + posible conflicto de KB"},
    {"customer": "Tomas Beltran", "phone": "+52 33 4444 1212", "reason": "Queja o frustracion", "message": "El asesor me dejo en visto y el bot me repite lo mismo.", "intent": "abandono_asesor", "confidence": 0.41, "wait": 24, "value": 13600, "stage": "Cita", "sentiment": "negative", "agent": None, "suggested": "Paola Nava", "ai_agent": "KB General", "missing": ["Asesor responsable"], "rule": "R-SENT-07: Frustracion + transferencia humana necesaria"},
    {"customer": "Renata Vega", "phone": "+52 81 1212 2020", "reason": "Pregunta no encontrada en KB", "message": "¿La garantia cubre bateria si uso la moto para reparto?", "intent": "garantia_reparto", "confidence": 0.36, "wait": 19, "value": 16700, "stage": "Nuevo", "sentiment": "neutral", "agent": None, "suggested": "Diego Salas", "ai_agent": "KB General", "missing": ["Cobertura de garantia para reparto"], "rule": "R-KB-404: Tema no cubierto"},
    {"customer": "Jose Luis Acosta", "phone": "+52 55 7788 9900", "reason": "Fuera de horario", "message": "Puedo ir ahorita con el enganche, pero no se si hay alguien.", "intent": "visita_fuera_horario", "confidence": 0.59, "wait": 35, "value": 22200, "stage": "Enganche listo", "sentiment": "positive", "agent": None, "suggested": "Luis Ortega", "ai_agent": "Agenda Bot", "missing": ["Sucursal abierta", "Asesor disponible"], "rule": "R-AH-01: Cierre potencial fuera de horario"},
    {"customer": "Brenda Pacheco", "phone": "+52 33 7070 8080", "reason": "Cliente pidio humano", "message": "Necesito hablar con supervisor por mi cita cancelada.", "intent": "supervisor_cita", "confidence": 0.46, "wait": 13, "value": 11900, "stage": "Cita", "sentiment": "negative", "agent": "Paola Nava", "suggested": "Paola Nava", "ai_agent": "Agenda Bot", "missing": ["Motivo cancelacion"], "rule": "R-HUM-02: Solicitud de supervisor"},
    {"customer": "Alonso Neri", "phone": "+52 81 5050 6060", "reason": "Factura fiscal / Datos incorrectos", "message": "El RFC salio mal y contabilidad ya me esta presionando.", "intent": "correccion_factura", "confidence": 0.33, "wait": 22, "value": 15400, "stage": "Sistema", "sentiment": "negative", "agent": None, "suggested": "Andrea Ruiz", "ai_agent": "Soporte Pagos", "missing": ["RFC correcto", "Regimen fiscal"], "rule": "R-INV-03: Correccion fiscal requiere humano"},
]


class PriorityBreakdown(BaseModel):
    score: int
    urgency: Urgency
    explanation: list[str]


class HumanAgent(BaseModel):
    id: str
    name: str
    email: str
    role: str
    status: Literal["online", "offline", "busy"]
    max_active_cases: int
    current_workload: int
    skills: list[str]


class AIAgent(BaseModel):
    id: str
    name: str
    purpose: str
    confidence_avg: float
    total_escalations: int
    active: bool = True


class HandoffCommandItem(BaseModel):
    id: str
    conversation_id: str
    customer_id: str
    customer_name: str
    phone: str
    channel: str
    status: HandoffStatus
    priority_score: int
    urgency: Urgency
    priority_explanation: list[str]
    handoff_reason: str
    detected_intent: str
    ai_confidence: float
    wait_time_seconds: int
    sla_deadline: datetime
    sla_status: SlaStatus
    recommended_action: str
    suggested_reply: str
    why_triggered: str
    risk_level: Literal["low", "medium", "high"]
    risk_explanation: str
    missing_fields: list[str]
    resolution_outcome: str | None = None
    feedback_type: str | None = None
    assigned_user_id: str | None = None
    assigned_agent_name: str | None = None
    suggested_agent_name: str
    ai_agent_id: str
    ai_agent_name: str
    lifecycle_stage: str
    estimated_value: int
    sentiment: Sentiment
    last_message: str
    last_message_at: datetime
    created_at: datetime
    resolved_at: datetime | None = None
    related_history: list[str]
    knowledge_gap_topic: str | None = None
    ai_rule: str


class SummaryCards(BaseModel):
    open_handoffs: int
    critical_cases: int
    average_wait_seconds: int
    sla_breaches: int
    ai_confidence_alerts: int
    high_value_leads_waiting: int
    high_value_potential_mxn: int
    unassigned_cases: int


class InsightCard(BaseModel):
    id: str
    label: str
    value: str
    detail: str
    trend: str
    sparkline: list[int]
    tone: Literal["good", "warning", "critical", "info"]


class RiskRadarItem(BaseModel):
    id: str
    title: str
    value: str
    detail: str
    trend: str
    severity: Literal["low", "medium", "high", "critical"]
    sparkline: list[int]


class HandoffCommandCenterResponse(BaseModel):
    items: list[HandoffCommandItem]
    total: int
    summary: SummaryCards
    insights: list[InsightCard]
    risk_radar: list[RiskRadarItem]
    human_agents: list[HumanAgent]
    ai_agents: list[AIAgent]
    updated_at: datetime


class TimelineEvent(BaseModel):
    id: str
    handoff_id: str
    event_type: str
    actor_type: Literal["ai", "human", "system"]
    actor_id: str | None = None
    description: str
    metadata: dict = Field(default_factory=dict)
    created_at: datetime


class TimelineResponse(BaseModel):
    items: list[TimelineEvent]


class AssignCommandBody(BaseModel):
    user_id: str


class ResolveCommandBody(BaseModel):
    resolution_outcome: str
    note: str | None = None


class FeedbackBody(BaseModel):
    feedback_type: FeedbackType
    note: str | None = None


class ReplyDraftBody(BaseModel):
    extra_context: str | None = None


class AssignmentRecommendation(BaseModel):
    suggested_agent: HumanAgent
    reason: str
    workload_info: str


class DraftResponse(BaseModel):
    draft: str
    safety_notes: list[str]
    source: Literal["mock", "stored"]


class HandoffDetailResponse(BaseModel):
    handoff: HandoffCommandItem
    timeline: list[TimelineEvent]


def _stable_uuid(*parts: object) -> UUID:
    return uuid5(NAMESPACE_URL, ":".join(str(p) for p in parts))


def _urgency_from_score(score: int) -> Urgency:
    if score >= 90:
        return "critical"
    if score >= 70:
        return "high"
    if score >= 45:
        return "medium"
    return "low"


def _score_handoff(*, wait_seconds: int, ai_confidence: float, sentiment: str, value: int, stage: str, reason: str, missing_fields: list[str]) -> PriorityBreakdown:
    score = 22
    explanation: list[str] = []
    wait_minutes = wait_seconds // 60
    wait_points = min(20, wait_minutes // 2)
    if wait_points:
        score += wait_points
        explanation.append(f"Espera acumulada aporta {wait_points} pts")
    confidence_points = max(0, int((0.75 - ai_confidence) * 45))
    if confidence_points:
        score += confidence_points
        explanation.append(f"Confianza IA baja ({int(ai_confidence * 100)}%)")
    if sentiment == "negative":
        score += 16
        explanation.append("Sentimiento negativo o frustracion detectada")
    elif sentiment == "positive":
        score += 4
        explanation.append("Cliente con intencion positiva")
    if value >= 22000:
        score += 12
        explanation.append("Lead de alto valor")
    elif value >= 15000:
        score += 7
        explanation.append("Oportunidad comercial relevante")
    if stage in {"Negociacion", "Enganche listo", "Cerrado"}:
        score += 10
        explanation.append("Etapa cercana a cierre")
    if reason in {"Error de sistema / Pago", "Factura fiscal / Datos incorrectos", "Queja o frustracion"}:
        score += 10
        explanation.append("Riesgo operacional o fiscal")
    if len(missing_fields) >= 2:
        score += 5
        explanation.append("Faltan datos criticos para responder seguro")
    score = max(0, min(100, score))
    return PriorityBreakdown(score=score, urgency=_urgency_from_score(score), explanation=explanation[:5])


def _sla_deadline(created_at: datetime, urgency: Urgency) -> datetime:
    return created_at + timedelta(minutes=SLA_MINUTES[urgency])


def _sla_status(deadline: datetime, urgency: Urgency, now: datetime) -> SlaStatus:
    remaining = (deadline - now).total_seconds()
    if remaining <= 0:
        return "breached"
    total = SLA_MINUTES[urgency] * 60
    if remaining <= total * 0.35:
        return "warning"
    return "healthy"


def _risk_level(score: int, sla_status: SlaStatus, sentiment: str) -> Literal["low", "medium", "high"]:
    if score >= 80 or sla_status == "breached" or sentiment == "negative":
        return "high"
    if score >= 55 or sla_status == "warning":
        return "medium"
    return "low"


def _draft_for(spec: dict) -> str:
    if "Factura" in spec["reason"]:
        return f"{spec['customer'].split()[0]}, gracias por avisarnos. Permiteme verificar los datos fiscales para enviarte la factura corregida a la brevedad. ¿Podrias confirmarme tu RFC, razon social y uso de CFDI?"
    if "Pago" in spec["reason"]:
        return f"{spec['customer'].split()[0]}, ya tomo tu caso para revisar el pago. No haremos otro cargo sin confirmar contigo; por favor enviame referencia o captura del error para validarlo."
    if "Documentos" in spec["reason"] or "Baja confianza" in spec["reason"]:
        return f"{spec['customer'].split()[0]}, reviso tu caso con credito para darte una respuesta segura. Antes de continuar confirmame los datos pendientes y un asesor validara si aplica excepcion."
    if "Negociacion" in spec["reason"]:
        return f"{spec['customer'].split()[0]}, gracias. Voy a revisar con gerencia la condicion comercial que solicitas y te confirmo una opcion viable sin prometer algo fuera de politica."
    return f"{spec['customer'].split()[0]}, ya tomo tu conversacion para ayudarte personalmente. Permiteme validar la informacion pendiente y te respondo con el siguiente paso correcto."


def _recommended_action(spec: dict) -> str:
    if "Factura" in spec["reason"]:
        return "Validar RFC, razon social y uso CFDI; corregir factura antes de cerrar."
    if "Pago" in spec["reason"]:
        return "Revisar referencia de pago, bloquear duplicidad y escalar a soporte si hay cargo."
    if "Agenda" in spec["reason"] or "horario" in spec["intent"]:
        return "Confirmar disponibilidad real de sucursal y proponer horario exacto."
    if "Negociacion" in spec["reason"]:
        return "Revisar margen y autorizar condicion comercial antes de prometer descuento."
    if "KB" in spec["reason"] or "Baja confianza" in spec["reason"]:
        return "Responder con humano y marcar brecha para entrenamiento/knowledge base."
    return "Tomar control, pedir dato faltante y documentar outcome al resolver."


def _human_agent_id(tenant_id: UUID, name_or_id: str | None) -> str | None:
    if not name_or_id:
        return None
    slug = name_or_id.lower().replace(" ", "-")
    return str(_stable_uuid(tenant_id, "agent", slug))


def _seed_to_item(spec: dict, tenant_id: UUID, index: int, now: datetime) -> HandoffCommandItem:
    created_at = now - timedelta(minutes=int(spec["wait"]), seconds=index * 17)
    wait_seconds = max(0, int((now - created_at).total_seconds()))
    score = _score_handoff(
        wait_seconds=wait_seconds,
        ai_confidence=float(spec["confidence"]),
        sentiment=str(spec["sentiment"]),
        value=int(spec["value"]),
        stage=str(spec["stage"]),
        reason=str(spec["reason"]),
        missing_fields=list(spec["missing"]),
    )
    urgency = score.urgency
    deadline = _sla_deadline(created_at, urgency)
    sla_status = _sla_status(deadline, urgency, now)
    risk_level = _risk_level(score.score, sla_status, str(spec["sentiment"]))
    ai_agent = next((a for a in AI_AGENTS if a["name"] == spec["ai_agent"]), AI_AGENTS[0])
    hid = _stable_uuid(tenant_id, "handoff-command-seed", index)
    return HandoffCommandItem(
        id=str(hid),
        conversation_id=str(_stable_uuid(tenant_id, "conversation", index)),
        customer_id=str(_stable_uuid(tenant_id, "customer", index)),
        customer_name=str(spec["customer"]),
        phone=str(spec["phone"]),
        channel="WhatsApp",
        status="assigned" if spec.get("agent") else "open",
        priority_score=score.score,
        urgency=urgency,
        priority_explanation=score.explanation,
        handoff_reason=str(spec["reason"]),
        detected_intent=str(spec["intent"]),
        ai_confidence=float(spec["confidence"]),
        wait_time_seconds=wait_seconds,
        sla_deadline=deadline,
        sla_status=sla_status,
        recommended_action=_recommended_action(spec),
        suggested_reply=_draft_for(spec),
        why_triggered=f"{spec['rule']} + {spec['message']}",
        risk_level=risk_level,
        risk_explanation="Puede afectar conversion, cumplimiento o confianza del cliente si el bot continua sin humano.",
        missing_fields=list(spec["missing"]),
        assigned_user_id=_human_agent_id(tenant_id, spec.get("agent")),
        assigned_agent_name=spec.get("agent"),
        suggested_agent_name=str(spec["suggested"]),
        ai_agent_id=str(ai_agent["id"]),
        ai_agent_name=str(ai_agent["name"]),
        lifecycle_stage=str(spec["stage"]),
        estimated_value=int(spec["value"]),
        sentiment=spec["sentiment"],
        last_message=str(spec["message"]),
        last_message_at=created_at + timedelta(minutes=max(0, int(spec["wait"]) - 1)),
        created_at=created_at,
        related_history=["3 pedidos previos", "2 tickets cerrados", "Ultimo contacto por WhatsApp"],
        knowledge_gap_topic=str(spec["intent"]) if "KB" in spec["reason"] or "Baja confianza" in spec["reason"] else None,
        ai_rule=str(spec["rule"]),
    )


def _payload_value(payload: dict | None, key: str, default: object = None) -> object:
    if not payload:
        return default
    return payload.get(key, default)


def _db_to_item(row: HumanHandoff, conversation: Conversation | None, customer: Customer | None, tenant_id: UUID, now: datetime) -> HandoffCommandItem:
    payload = row.payload or {}
    name = str(_payload_value(payload, "customer", None) or customer.name if customer and customer.name else "Cliente sin nombre")
    last_message = str(_payload_value(payload, "last_inbound", None) or _payload_value(payload, "last_inbound_text", None) or row.reason)
    reason = str(_payload_value(payload, "handoff_reason", None) or _payload_value(payload, "reason_code", None) or row.reason)
    confidence = float(_payload_value(payload, "ai_confidence", 0.46) or 0.46)
    stage = str(_payload_value(payload, "lifecycle_stage", None) or (customer.stage if customer else None) or (conversation.current_stage if conversation else "Nuevo"))
    sentiment = str(_payload_value(payload, "sentiment", None) or (customer.attrs or {}).get("sentiment") if customer else "neutral")
    if sentiment not in ("positive", "neutral", "negative"):
        sentiment = "neutral"
    value = int(_payload_value(payload, "estimated_value", None) or (customer.attrs or {}).get("estimated_value", 14500) if customer else 14500)
    missing = list(_payload_value(payload, "missing_fields", None) or _payload_value(payload, "docs_pendientes", None) or [])
    wait_seconds = max(0, int((now - row.requested_at).total_seconds()))
    score = _score_handoff(wait_seconds=wait_seconds, ai_confidence=confidence, sentiment=sentiment, value=value, stage=stage, reason=reason, missing_fields=missing)
    urgency = str(_payload_value(payload, "urgency", score.urgency))
    if urgency not in SLA_MINUTES:
        urgency = score.urgency
    deadline = _sla_deadline(row.requested_at, urgency)  # type: ignore[arg-type]
    sla_status = _sla_status(deadline, urgency, now)  # type: ignore[arg-type]
    risk_level = _risk_level(score.score, sla_status, sentiment)
    ai_agent_name = str(_payload_value(payload, "ai_agent_name", "Ventas Pro"))
    ai_agent = next((a for a in AI_AGENTS if a["name"] == ai_agent_name), AI_AGENTS[0])
    return HandoffCommandItem(
        id=str(row.id),
        conversation_id=str(row.conversation_id),
        customer_id=str(conversation.customer_id if conversation else _stable_uuid(tenant_id, "customer", row.id)),
        customer_name=name,
        phone=str(customer.phone_e164 if customer else _payload_value(payload, "phone", "+52 55 0000 0000")),
        channel=str(conversation.channel if conversation else "WhatsApp"),
        status=row.status if row.status in ("open", "assigned", "resolved", "escalated") else "open",
        priority_score=score.score,
        urgency=urgency,  # type: ignore[arg-type]
        priority_explanation=score.explanation,
        handoff_reason=reason,
        detected_intent=str(_payload_value(payload, "detected_intent", _payload_value(payload, "last_intent", "intervencion_humana"))),
        ai_confidence=confidence,
        wait_time_seconds=wait_seconds,
        sla_deadline=deadline,
        sla_status=sla_status,
        recommended_action=str(_payload_value(payload, "recommended_action", _payload_value(payload, "suggested_next_action", "Tomar control y validar datos pendientes."))),
        suggested_reply=str(_payload_value(payload, "suggested_reply", _draft_for({"customer": name, "reason": reason}))),
        why_triggered=str(_payload_value(payload, "why_triggered", f"{row.reason}. El bot detecto que continuar automaticamente podria ser riesgoso.")),
        risk_level=risk_level,
        risk_explanation=str(_payload_value(payload, "risk_explanation", "Riesgo de mala experiencia o respuesta no trazable.")),
        missing_fields=missing,
        resolution_outcome=_payload_value(payload, "resolution_outcome", None),  # type: ignore[arg-type]
        feedback_type=_payload_value(payload, "feedback_type", None),  # type: ignore[arg-type]
        assigned_user_id=str(row.assigned_user_id) if row.assigned_user_id else None,
        assigned_agent_name=str(_payload_value(payload, "assigned_agent_name", None)) if row.assigned_user_id else None,
        suggested_agent_name=str(_payload_value(payload, "suggested_agent_name", "Andrea Ruiz")),
        ai_agent_id=str(ai_agent["id"]),
        ai_agent_name=str(ai_agent["name"]),
        lifecycle_stage=stage,
        estimated_value=value,
        sentiment=sentiment,  # type: ignore[arg-type]
        last_message=last_message,
        last_message_at=conversation.last_activity_at if conversation else row.requested_at,
        created_at=row.requested_at,
        resolved_at=row.resolved_at,
        related_history=list(_payload_value(payload, "related_history", ["Conversacion activa", "Historial de IA disponible"])),
        knowledge_gap_topic=_payload_value(payload, "knowledge_gap_topic", None),  # type: ignore[arg-type]
        ai_rule=str(_payload_value(payload, "ai_rule", "R-HUMAN-HANDOFF: escalacion generada por el runner")),
    )


async def _load_db_items(session: AsyncSession, tenant_id: UUID, now: datetime) -> list[HandoffCommandItem]:
    rows = (
        await session.execute(
            select(HumanHandoff, Conversation, Customer)
            .outerjoin(Conversation, Conversation.id == HumanHandoff.conversation_id)
            .outerjoin(Customer, Customer.id == Conversation.customer_id)
            .where(HumanHandoff.tenant_id == tenant_id)
            .order_by(HumanHandoff.requested_at.desc())
            .limit(80)
        )
    ).all()
    return [_db_to_item(h, c, customer, tenant_id, now) for h, c, customer in rows]


async def _load_human_agents(session: AsyncSession, tenant_id: UUID, items: list[HandoffCommandItem]) -> list[HumanAgent]:
    tenant_result = await session.execute(select(Tenant).where(Tenant.id == tenant_id))
    _tenant = tenant_result.scalar_one_or_none()
    is_demo = _tenant is not None and _tenant.is_demo

    db_users = (
        await session.execute(
            select(TenantUser).where(TenantUser.tenant_id == tenant_id).order_by(TenantUser.created_at.asc()).limit(20)
        )
    ).scalars().all()
    workload_by_user: dict[str, int] = {}
    for item in items:
        if item.assigned_user_id and item.status != "resolved":
            workload_by_user[item.assigned_user_id] = workload_by_user.get(item.assigned_user_id, 0) + 1

    agents: list[HumanAgent] = []
    for user in db_users:
        display_name = user.email.split("@")[0].replace(".", " ").title()
        agents.append(
            HumanAgent(
                id=str(user.id),
                name=display_name,
                email=user.email,
                role=user.role,
                status="online" if workload_by_user.get(str(user.id), 0) < 5 else "busy",
                max_active_cases=10,
                current_workload=workload_by_user.get(str(user.id), 0),
                skills=["ventas", "soporte", "documentos"],
            )
        )

    # Only pad with demo fixture agents for demo tenants
    if is_demo:
        existing_names = {a.name for a in agents}
        for spec in DEMO_HUMAN_AGENTS:
            if spec["name"] in existing_names:
                continue
            agents.append(
                HumanAgent(
                    id=str(_stable_uuid(tenant_id, "agent", spec["id"])),
                    name=str(spec["name"]),
                    email=str(spec["email"]),
                    role=str(spec["role"]),
                    status=spec["status"],  # type: ignore[arg-type]
                    max_active_cases=int(spec["max_active_cases"]),
                    current_workload=int(spec["current_workload"]),
                    skills=list(spec["skills"]),
                )
            )
    return agents[:12]


def _build_items_with_seed(db_items: list[HandoffCommandItem], tenant_id: UUID, now: datetime) -> list[HandoffCommandItem]:
    items = list(db_items)
    existing_ids = {item.id for item in items}
    for index, spec in enumerate(SEED_HANDOFFS, start=1):
        item = _seed_to_item(spec, tenant_id, index, now)
        if item.id not in existing_ids:
            items.append(item)
    return items


def _apply_filters(
    items: list[HandoffCommandItem],
    *,
    urgency: str | None,
    reason: str | None,
    agent: str | None,
    waiting_time: str | None,
    sla_status: str | None,
    lifecycle_stage: str | None,
    ai_agent: str | None,
    channel: str | None,
    sentiment: str | None,
    high_value_only: bool,
    status_filter: str | None,
    q: str | None,
) -> list[HandoffCommandItem]:
    out = items
    if urgency and urgency != "all":
        out = [item for item in out if item.urgency == urgency]
    if reason and reason != "all":
        out = [item for item in out if item.handoff_reason == reason]
    if agent and agent != "all":
        out = [item for item in out if item.assigned_user_id == agent or item.suggested_agent_name == agent or item.assigned_agent_name == agent]
    if waiting_time and waiting_time != "all":
        thresholds = {"lt_10": (0, 10), "10_30": (10, 30), "gt_30": (30, 10_000)}
        lo, hi = thresholds.get(waiting_time, (0, 10_000))
        out = [item for item in out if lo <= item.wait_time_seconds / 60 < hi]
    if sla_status and sla_status != "all":
        out = [item for item in out if item.sla_status == sla_status]
    if lifecycle_stage and lifecycle_stage != "all":
        out = [item for item in out if item.lifecycle_stage == lifecycle_stage]
    if ai_agent and ai_agent != "all":
        out = [item for item in out if item.ai_agent_id == ai_agent or item.ai_agent_name == ai_agent]
    if channel and channel != "all":
        out = [item for item in out if item.channel.lower() == channel.lower()]
    if sentiment and sentiment != "all":
        out = [item for item in out if item.sentiment == sentiment]
    if high_value_only:
        out = [item for item in out if item.estimated_value >= 18000]
    if status_filter and status_filter != "all":
        out = [item for item in out if item.status == status_filter]
    if q:
        needle = q.strip().lower()
        out = [
            item
            for item in out
            if needle in item.customer_name.lower()
            or needle in item.phone.lower()
            or needle in item.last_message.lower()
            or needle in item.handoff_reason.lower()
        ]
    return out


def _sort_items(items: list[HandoffCommandItem], sort: str | None) -> list[HandoffCommandItem]:
    if sort == "wait_time_desc":
        return sorted(items, key=lambda item: item.wait_time_seconds, reverse=True)
    if sort == "estimated_value_desc":
        return sorted(items, key=lambda item: item.estimated_value, reverse=True)
    if sort == "ai_confidence_asc":
        return sorted(items, key=lambda item: item.ai_confidence)
    if sort == "sla_deadline_asc":
        return sorted(items, key=lambda item: item.sla_deadline)
    return sorted(items, key=lambda item: item.priority_score, reverse=True)


def _summary(items: list[HandoffCommandItem]) -> SummaryCards:
    active = [item for item in items if item.status != "resolved"]
    waits = [item.wait_time_seconds for item in active]
    high_value = [item for item in active if item.estimated_value >= 18000]
    return SummaryCards(
        open_handoffs=len([item for item in active if item.status == "open"]),
        critical_cases=len([item for item in active if item.urgency == "critical"]),
        average_wait_seconds=int(sum(waits) / max(1, len(waits))),
        sla_breaches=len([item for item in active if item.sla_status == "breached"]),
        ai_confidence_alerts=len([item for item in active if item.ai_confidence < 0.45]),
        high_value_leads_waiting=len(high_value),
        high_value_potential_mxn=sum(item.estimated_value for item in high_value),
        unassigned_cases=len([item for item in active if item.assigned_user_id is None]),
    )


def _insights(items: list[HandoffCommandItem]) -> list[InsightCard]:
    reasons: dict[str, int] = {}
    agents: dict[str, int] = {}
    for item in items:
        reasons[item.handoff_reason] = reasons.get(item.handoff_reason, 0) + 1
        agents[item.ai_agent_name] = agents.get(item.ai_agent_name, 0) + 1
    top_reason = max(reasons.items(), key=lambda pair: pair[1])[0] if reasons else "Sin datos"
    top_ai = max(agents.items(), key=lambda pair: pair[1])[0] if agents else "Sin datos"
    return [
        InsightCard(id="reason", label="Razon mas comun hoy", value=top_reason, detail=f"{reasons.get(top_reason, 0)} handoffs", trend="+34% vs ayer", sparkline=[2, 2, 4, 5, 4, 7, 8, 11, 8, 12], tone="info"),
        InsightCard(id="ai-agent", label="Agente IA con mas escalaciones", value=top_ai, detail=f"{agents.get(top_ai, 0)} handoffs", trend="+18%", sparkline=[3, 4, 3, 6, 5, 9, 8, 7, 10, 9], tone="warning"),
        InsightCard(id="slowest", label="Cola mas lenta", value="Facturacion", detail="Prom. 28m 36s", trend="+6m", sparkline=[4, 5, 6, 6, 8, 9, 12, 13, 14, 16], tone="critical"),
        InsightCard(id="kb-gap", label="Brecha de conocimiento", value="Politica de descuentos", detail="12 consultas sin respuesta", trend="+5", sparkline=[1, 1, 2, 2, 4, 4, 7, 6, 9, 10], tone="warning"),
        InsightCard(id="after-hours", label="Pico fuera de horario", value="+38%", detail="7 PM - 11 PM", trend="+11 PM", sparkline=[1, 2, 1, 2, 3, 3, 6, 8, 9, 11], tone="info"),
        InsightCard(id="conversion-risk", label="Oportunidades en riesgo", value=f"${sum(i.estimated_value for i in items if i.risk_level == 'high'):,} MXN", detail="22 leads", trend="+9%", sparkline=[5, 5, 6, 7, 9, 8, 12, 14, 13, 18], tone="good"),
    ]


def _risk_radar(items: list[HandoffCommandItem]) -> list[RiskRadarItem]:
    active = [item for item in items if item.status != "resolved"]
    return [
        RiskRadarItem(id="intent-failures", title="Fallas por intencion repetida", value=str(len([i for i in active if i.ai_confidence < 0.5])), detail="Intenciones con baja confianza", trend="+18% vs ayer", severity="high", sparkline=[4, 5, 7, 6, 8, 11, 10, 13, 12, 16]),
        RiskRadarItem(id="sla-breach", title="Tendencia de brechas SLA", value=str(len([i for i in active if i.sla_status == "breached"])), detail="Casos fuera de objetivo", trend="+50% vs ayer", severity="critical", sparkline=[1, 2, 2, 3, 4, 3, 6, 7, 8, 9]),
        RiskRadarItem(id="unassigned", title="Casos sin asignar", value=str(len([i for i in active if i.assigned_user_id is None])), detail="Requieren owner", trend="+83% vs ayer", severity="high", sparkline=[2, 3, 5, 4, 6, 8, 9, 11, 10, 13]),
        RiskRadarItem(id="high-value", title="Leads de alto valor esperando", value=str(len([i for i in active if i.estimated_value >= 18000])), detail="$82,450 MXN potencial", trend="+4", severity="medium", sparkline=[2, 2, 4, 3, 5, 7, 6, 9, 8, 10]),
        RiskRadarItem(id="low-confidence", title="Cluster baja confianza IA", value=str(len([i for i in active if i.ai_confidence < 0.4])), detail="Prom. 28%", trend="+9%", severity="high", sparkline=[3, 4, 5, 4, 7, 6, 8, 10, 9, 12]),
        RiskRadarItem(id="missing-kb", title="Respuestas faltantes en KB", value=str(len([i for i in active if i.knowledge_gap_topic])), detail="Temas criticos", trend="+6", severity="medium", sparkline=[2, 2, 3, 4, 4, 6, 8, 7, 9, 12]),
    ]


def _timeline_for(item: HandoffCommandItem, payload: dict | None = None) -> list[TimelineEvent]:
    stored = payload.get("timeline", []) if payload else []
    events = [
        TimelineEvent(id=str(_stable_uuid(item.id, "created")), handoff_id=item.id, event_type="handoff_created", actor_type="ai", description=f"IA escalo por {item.handoff_reason}", metadata={"confidence": item.ai_confidence}, created_at=item.created_at),
        TimelineEvent(id=str(_stable_uuid(item.id, "priority")), handoff_id=item.id, event_type="priority_scored", actor_type="system", description=f"Prioridad calculada en {item.priority_score}/100", metadata={"urgency": item.urgency}, created_at=item.created_at + timedelta(seconds=15)),
    ]
    if item.assigned_user_id:
        events.append(TimelineEvent(id=str(_stable_uuid(item.id, "assigned")), handoff_id=item.id, event_type="handoff_assigned", actor_type="human", actor_id=item.assigned_user_id, description=f"Asignado a {item.assigned_agent_name or item.suggested_agent_name}", metadata={}, created_at=item.created_at + timedelta(minutes=1)))
    if item.sla_status == "breached":
        events.append(TimelineEvent(id=str(_stable_uuid(item.id, "breach")), handoff_id=item.id, event_type="sla_breached", actor_type="system", description="SLA vencido, requiere atencion inmediata", metadata={"deadline": item.sla_deadline.isoformat()}, created_at=item.sla_deadline))
    for raw in stored:
        try:
            events.append(TimelineEvent(**raw))
        except Exception:
            continue
    return sorted(events, key=lambda event: event.created_at)


def _can_operate(user: AuthUser) -> bool:
    return user.role in {"operator", "tenant_admin", "manager", "supervisor", "ai_reviewer", "superadmin"}


async def _publish(request: Request, tenant_id: UUID, conversation_id: str, event_type: str, payload: dict | None = None) -> None:
    try:
        redis = Redis.from_url(get_settings().redis_url)
        try:
            await publish_event(redis, tenant_id=str(tenant_id), conversation_id=conversation_id, event={"type": event_type, "payload": payload or {}})
        finally:
            await redis.aclose()
    except Exception:
        pass


async def _get_real_handoff(session: AsyncSession, tenant_id: UUID, handoff_id: str) -> HumanHandoff | None:
    try:
        parsed = UUID(handoff_id)
    except ValueError:
        return None
    return (
        await session.execute(
            select(HumanHandoff).where(HumanHandoff.id == parsed, HumanHandoff.tenant_id == tenant_id)
        )
    ).scalar_one_or_none()


async def _all_items(session: AsyncSession, tenant_id: UUID) -> list[HandoffCommandItem]:
    now = datetime.now(UTC)
    db_items = await _load_db_items(session, tenant_id, now)

    # Only inject seed handoffs for demo tenants
    tenant_result = await session.execute(select(Tenant).where(Tenant.id == tenant_id))
    _tenant = tenant_result.scalar_one_or_none()
    if _tenant is not None and _tenant.is_demo:
        return _build_items_with_seed(db_items, tenant_id, now)
    return db_items


async def build_handoff_command_center_snapshot(
    session: AsyncSession,
    tenant_id: UUID,
) -> HandoffCommandCenterResponse:
    items = await _all_items(session, tenant_id)
    agents = await _load_human_agents(session, tenant_id, items)
    return HandoffCommandCenterResponse(
        items=_sort_items(items, "priority_score_desc"),
        total=len(items),
        summary=_summary(items),
        insights=_insights(items),
        risk_radar=_risk_radar(items),
        human_agents=agents,
        ai_agents=[AIAgent(**agent) for agent in AI_AGENTS],
        updated_at=datetime.now(UTC),
    )


async def _find_item(session: AsyncSession, tenant_id: UUID, handoff_id: str) -> HandoffCommandItem:
    for item in await _all_items(session, tenant_id):
        if item.id == handoff_id:
            return item
    raise HTTPException(status.HTTP_404_NOT_FOUND, "handoff not found")


async def _recommend_agent(item: HandoffCommandItem, agents: list[HumanAgent]) -> AssignmentRecommendation:
    keywords = {
        "Factura fiscal / Datos incorrectos": "facturacion",
        "Documentos incompletos": "documentos",
        "Negociacion de precio": "negociacion",
        "Disponibilidad / Agenda": "agenda",
        "Error de sistema / Pago": "pagos",
        "Pregunta no encontrada en KB": "kb",
    }
    skill = keywords.get(item.handoff_reason, "ventas")
    candidates = [
        agent
        for agent in agents
        if agent.status == "online" and agent.current_workload < agent.max_active_cases
    ]
    if not candidates:
        candidates = agents
    candidates = sorted(
        candidates,
        key=lambda agent: (
            0 if skill in agent.skills else 1,
            agent.current_workload / max(1, agent.max_active_cases),
        ),
    )
    selected = candidates[0]
    return AssignmentRecommendation(
        suggested_agent=selected,
        reason=f"Mejor match por habilidad '{skill}', disponibilidad {selected.status} y carga {selected.current_workload}/{selected.max_active_cases}.",
        workload_info=f"{selected.name} tiene {selected.current_workload} casos activos de {selected.max_active_cases}.",
    )


@router.get("", response_model=HandoffCommandCenterResponse)
async def command_center(
    _user: AuthedUser,
    tenant_id: TenantId,
    session: DbSession,
    urgency: str | None = Query(None),
    reason: str | None = Query(None),
    agent: str | None = Query(None),
    waiting_time: str | None = Query(None),
    sla_status: str | None = Query(None),
    lifecycle_stage: str | None = Query(None),
    ai_agent: str | None = Query(None),
    channel: str | None = Query(None),
    sentiment: str | None = Query(None),
    high_value_only: bool = Query(False),
    status_filter: str | None = Query(None, alias="status"),
    sort: str | None = Query("priority_score_desc"),
    q: str | None = Query(None, max_length=120),
) -> HandoffCommandCenterResponse:
    items = await _all_items(session, tenant_id)
    agents = await _load_human_agents(session, tenant_id, items)
    filtered = _apply_filters(
        items,
        urgency=urgency,
        reason=reason,
        agent=agent,
        waiting_time=waiting_time,
        sla_status=sla_status,
        lifecycle_stage=lifecycle_stage,
        ai_agent=ai_agent,
        channel=channel,
        sentiment=sentiment,
        high_value_only=high_value_only,
        status_filter=status_filter,
        q=q,
    )
    sorted_items = _sort_items(filtered, sort)
    return HandoffCommandCenterResponse(
        items=sorted_items,
        total=len(sorted_items),
        summary=_summary(items),
        insights=_insights(items),
        risk_radar=_risk_radar(items),
        human_agents=agents,
        ai_agents=[AIAgent(**agent) for agent in AI_AGENTS],
        updated_at=datetime.now(UTC),
    )


@router.get("/{handoff_id}", response_model=HandoffDetailResponse)
async def get_handoff_detail(handoff_id: str, _user: AuthedUser, tenant_id: TenantId, session: DbSession) -> HandoffDetailResponse:
    item = await _find_item(session, tenant_id, handoff_id)
    row = await _get_real_handoff(session, tenant_id, handoff_id)
    return HandoffDetailResponse(handoff=item, timeline=_timeline_for(item, row.payload if row else None))


@router.get("/{handoff_id}/timeline", response_model=TimelineResponse)
async def get_timeline(handoff_id: str, _user: AuthedUser, tenant_id: TenantId, session: DbSession) -> TimelineResponse:
    item = await _find_item(session, tenant_id, handoff_id)
    row = await _get_real_handoff(session, tenant_id, handoff_id)
    return TimelineResponse(items=_timeline_for(item, row.payload if row else None))


@router.post("/{handoff_id}/take", response_model=HandoffCommandItem)
async def take_handoff(handoff_id: str, request: Request, user: AuthedUser, tenant_id: TenantId, session: DbSession) -> HandoffCommandItem:
    if not _can_operate(user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "role cannot take handoffs")
    row = await _get_real_handoff(session, tenant_id, handoff_id)
    if row is not None:
        payload = dict(row.payload or {})
        payload["assigned_agent_name"] = user.email.split("@")[0].replace(".", " ").title()
        payload["timeline"] = payload.get("timeline", []) + [
            TimelineEvent(id=str(_stable_uuid(handoff_id, "take", datetime.now(UTC).isoformat())), handoff_id=handoff_id, event_type="handoff_taken", actor_type="human", actor_id=str(user.user_id), description=f"{user.email} tomo el caso", metadata={}, created_at=datetime.now(UTC)).model_dump(mode="json")
        ]
        await session.execute(update(HumanHandoff).where(HumanHandoff.id == row.id).values(assigned_user_id=user.user_id, status="assigned", payload=payload))
        await session.commit()
        await _publish(request, tenant_id, str(row.conversation_id), "handoff_taken", {"handoff_id": handoff_id})
    item = await _find_item(session, tenant_id, handoff_id)
    return item.model_copy(update={"status": "assigned", "assigned_user_id": str(user.user_id), "assigned_agent_name": user.email.split("@")[0].replace(".", " ").title()})


@router.post("/{handoff_id}/assign", response_model=HandoffCommandItem)
async def assign_handoff_command(handoff_id: str, body: AssignCommandBody, request: Request, user: AuthedUser, tenant_id: TenantId, session: DbSession) -> HandoffCommandItem:
    if not _can_operate(user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "role cannot assign handoffs")
    item = await _find_item(session, tenant_id, handoff_id)
    row = await _get_real_handoff(session, tenant_id, handoff_id)
    agents = await _load_human_agents(session, tenant_id, await _all_items(session, tenant_id))
    assigned = next((agent for agent in agents if agent.id == body.user_id), None)
    assigned_name = assigned.name if assigned else "Operador asignado"
    if row is not None:
        payload = dict(row.payload or {})
        payload["assigned_agent_name"] = assigned_name
        payload["timeline"] = payload.get("timeline", []) + [
            TimelineEvent(id=str(_stable_uuid(handoff_id, "assign", datetime.now(UTC).isoformat())), handoff_id=handoff_id, event_type="handoff_assigned", actor_type="human", actor_id=str(user.user_id), description=f"Asignado a {assigned_name}", metadata={"assigned_user_id": body.user_id}, created_at=datetime.now(UTC)).model_dump(mode="json")
        ]
        try:
            parsed_user_id = UUID(body.user_id)
        except ValueError:
            parsed_user_id = user.user_id
        await session.execute(update(HumanHandoff).where(HumanHandoff.id == row.id).values(assigned_user_id=parsed_user_id, status="assigned", payload=payload))
        await session.commit()
        await _publish(request, tenant_id, str(row.conversation_id), "handoff_assigned", {"handoff_id": handoff_id})
    return item.model_copy(update={"status": "assigned", "assigned_user_id": body.user_id, "assigned_agent_name": assigned_name})


@router.post("/{handoff_id}/resolve", response_model=HandoffCommandItem)
async def resolve_handoff_command(handoff_id: str, body: ResolveCommandBody, request: Request, user: AuthedUser, tenant_id: TenantId, session: DbSession) -> HandoffCommandItem:
    if not _can_operate(user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "role cannot resolve handoffs")
    item = await _find_item(session, tenant_id, handoff_id)
    row = await _get_real_handoff(session, tenant_id, handoff_id)
    resolved_at = datetime.now(UTC)
    if row is not None:
        payload = dict(row.payload or {})
        payload.update({"resolution_outcome": body.resolution_outcome, "resolution_note": body.note, "resolved_by": str(user.user_id)})
        payload["timeline"] = payload.get("timeline", []) + [
            TimelineEvent(id=str(_stable_uuid(handoff_id, "resolve", resolved_at.isoformat())), handoff_id=handoff_id, event_type="handoff_resolved", actor_type="human", actor_id=str(user.user_id), description=f"Resuelto: {body.resolution_outcome}", metadata={"note": body.note}, created_at=resolved_at).model_dump(mode="json")
        ]
        await session.execute(update(HumanHandoff).where(HumanHandoff.id == row.id).values(status="resolved", resolved_at=resolved_at, payload=payload))
        await session.commit()
        await _publish(request, tenant_id, str(row.conversation_id), "handoff_resolved", {"handoff_id": handoff_id})
    return item.model_copy(update={"status": "resolved", "resolution_outcome": body.resolution_outcome, "resolved_at": resolved_at})


@router.post("/{handoff_id}/feedback", response_model=HandoffCommandItem)
async def submit_feedback(handoff_id: str, body: FeedbackBody, request: Request, user: AuthedUser, tenant_id: TenantId, session: DbSession) -> HandoffCommandItem:
    item = await _find_item(session, tenant_id, handoff_id)
    row = await _get_real_handoff(session, tenant_id, handoff_id)
    if row is not None:
        payload = dict(row.payload or {})
        payload["feedback_type"] = body.feedback_type
        payload["feedback_note"] = body.note
        if body.feedback_type == "knowledge_gap":
            payload["knowledge_gap_topic"] = item.detected_intent
        payload["timeline"] = payload.get("timeline", []) + [
            TimelineEvent(id=str(_stable_uuid(handoff_id, "feedback", datetime.now(UTC).isoformat())), handoff_id=handoff_id, event_type="feedback_submitted", actor_type="human", actor_id=str(user.user_id), description=f"Feedback: {body.feedback_type}", metadata={"note": body.note}, created_at=datetime.now(UTC)).model_dump(mode="json")
        ]
        await session.execute(update(HumanHandoff).where(HumanHandoff.id == row.id).values(payload=payload))
        await session.commit()
        await _publish(request, tenant_id, str(row.conversation_id), "handoff_feedback", {"handoff_id": handoff_id, "feedback_type": body.feedback_type})
    return item.model_copy(update={"feedback_type": body.feedback_type, "knowledge_gap_topic": item.detected_intent if body.feedback_type == "knowledge_gap" else item.knowledge_gap_topic})


@router.post("/{handoff_id}/generate-reply", response_model=DraftResponse)
@router.post("/{handoff_id}/reply-draft", response_model=DraftResponse)
async def generate_reply_draft(handoff_id: str, body: ReplyDraftBody, request: Request, user: AuthedUser, tenant_id: TenantId, session: DbSession) -> DraftResponse:
    item = await _find_item(session, tenant_id, handoff_id)
    row = await _get_real_handoff(session, tenant_id, handoff_id)
    draft = item.suggested_reply
    if body.extra_context:
        draft = f"{draft}\n\nContexto adicional a considerar: {body.extra_context.strip()}"
    if row is not None:
        payload = dict(row.payload or {})
        payload["suggested_reply"] = draft
        payload["timeline"] = payload.get("timeline", []) + [
            TimelineEvent(id=str(_stable_uuid(handoff_id, "draft", datetime.now(UTC).isoformat())), handoff_id=handoff_id, event_type="reply_draft_generated", actor_type="ai", actor_id=str(user.user_id), description="Borrador IA generado para revision humana", metadata={}, created_at=datetime.now(UTC)).model_dump(mode="json")
        ]
        await session.execute(update(HumanHandoff).where(HumanHandoff.id == row.id).values(payload=payload))
        await session.commit()
        await _publish(request, tenant_id, str(row.conversation_id), "handoff_reply_draft", {"handoff_id": handoff_id})
    return DraftResponse(draft=draft, safety_notes=["No se auto-envio al cliente.", "Validar datos fiscales, precio, stock o credito antes de usar.", "El humano debe revisar tono y politica."], source="mock")


@router.post("/{handoff_id}/recommend-agent", response_model=AssignmentRecommendation)
async def recommend_agent(handoff_id: str, _user: AuthedUser, tenant_id: TenantId, session: DbSession) -> AssignmentRecommendation:
    items = await _all_items(session, tenant_id)
    item = next((candidate for candidate in items if candidate.id == handoff_id), None)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "handoff not found")
    agents = await _load_human_agents(session, tenant_id, items)
    return await _recommend_agent(item, agents)
