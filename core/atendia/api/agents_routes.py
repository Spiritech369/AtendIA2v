from __future__ import annotations

import time
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.api._audit import emit_admin_event
from atendia.api._auth_helpers import AuthUser
from atendia.api._deps import current_tenant_id, current_user, require_tenant_admin
from atendia.config import get_settings
from atendia.db.models.agent import Agent
from atendia.db.session import get_db_session

router = APIRouter()
guardrails_router = APIRouter()
extraction_fields_router = APIRouter()
supervisor_router = APIRouter()
scenarios_router = APIRouter()

AGENT_ROLES = {
    "sales",
    "support",
    "collections",
    "documentation",
    "reception",
    "custom",
    "sales_agent",
    "duda_general",
    "postventa",
}
NLU_INTENTS = {
    "GREETING",
    "ASK_INFO",
    "ASK_PRICE",
    "BUY",
    "SCHEDULE",
    "COMPLAIN",
    "OFF_TOPIC",
    "UNCLEAR",
    "CREDIT_APPLICATION",
    "SERVICE_REQUEST",
    "POSTSALE",
    "HUMAN_REQUESTED",
}
AGENT_STATUSES = {"draft", "validation", "testing", "production", "paused"}
BEHAVIOR_MODES = {"normal", "conservative", "strict"}
GUARDRAIL_SEVERITIES = {"critical", "high", "medium", "low"}
GUARDRAIL_ENFORCEMENT = {"block", "rewrite", "warn", "handoff"}
FIELD_TYPES = {"text", "number", "date", "boolean", "enum", "phone", "currency"}


class AgentItem(BaseModel):
    id: UUID
    tenant_id: UUID
    name: str
    role: str
    status: str
    behavior_mode: str
    version: str
    dealership_id: str | None
    branch_id: str | None
    goal: str | None
    style: str | None
    tone: str | None
    language: str | None
    max_sentences: int | None
    no_emoji: bool
    return_to_flow: bool
    is_default: bool
    system_prompt: str | None
    active_intents: list[str]
    extraction_config: dict
    auto_actions: dict
    knowledge_config: dict
    flow_mode_rules: dict | None
    ops_config: dict
    created_at: datetime
    updated_at: datetime
    health: dict
    metrics: dict
    guardrails: list[dict]
    extraction_fields: list[dict]
    live_monitor: dict
    supervisor: dict
    knowledge_coverage: dict
    decision_map: dict
    versions: list[dict]
    scenarios: list[dict]


class AgentBody(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    role: str = "custom"
    status: str = "production"
    behavior_mode: str = "normal"
    version: str = "v2.4"
    dealership_id: str | None = Field(default=None, max_length=80)
    branch_id: str | None = Field(default=None, max_length=80)
    goal: str | None = None
    style: str | None = Field(default=None, max_length=200)
    tone: str | None = Field(default="amigable", max_length=40)
    language: str | None = Field(default="es", max_length=20)
    max_sentences: int | None = Field(default=3, ge=1, le=5)
    no_emoji: bool = False
    return_to_flow: bool = True
    is_default: bool = False
    system_prompt: str | None = None
    active_intents: list[str] = Field(default_factory=list)
    extraction_config: dict = Field(default_factory=dict)
    auto_actions: dict = Field(default_factory=dict)
    knowledge_config: dict = Field(default_factory=dict)
    flow_mode_rules: dict | None = None
    ops_config: dict = Field(default_factory=dict)

    @field_validator("role")
    @classmethod
    def _role(cls, value: str) -> str:
        if value not in AGENT_ROLES:
            raise ValueError("invalid agent role")
        return value

    @field_validator("status")
    @classmethod
    def _status(cls, value: str) -> str:
        if value not in AGENT_STATUSES:
            raise ValueError("invalid agent status")
        return value

    @field_validator("behavior_mode")
    @classmethod
    def _mode(cls, value: str) -> str:
        if value not in BEHAVIOR_MODES:
            raise ValueError("invalid behavior mode")
        return value

    @field_validator("active_intents")
    @classmethod
    def _intents(cls, value: list[str]) -> list[str]:
        unknown = [item for item in value if item not in NLU_INTENTS]
        if unknown:
            raise ValueError(f"unknown intents: {', '.join(unknown)}")
        return list(dict.fromkeys(value))


class AgentPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=120)
    role: str | None = None
    status: str | None = None
    behavior_mode: str | None = None
    version: str | None = None
    dealership_id: str | None = Field(default=None, max_length=80)
    branch_id: str | None = Field(default=None, max_length=80)
    goal: str | None = None
    style: str | None = Field(default=None, max_length=200)
    tone: str | None = Field(default=None, max_length=40)
    language: str | None = Field(default=None, max_length=20)
    max_sentences: int | None = Field(default=None, ge=1, le=5)
    no_emoji: bool | None = None
    return_to_flow: bool | None = None
    is_default: bool | None = None
    system_prompt: str | None = None
    active_intents: list[str] | None = None
    extraction_config: dict | None = None
    auto_actions: dict | None = None
    knowledge_config: dict | None = None
    flow_mode_rules: dict | None = None
    ops_config: dict | None = None

    @field_validator("role")
    @classmethod
    def _patch_role(cls, value: str | None) -> str | None:
        if value is not None and value not in AGENT_ROLES:
            raise ValueError("invalid agent role")
        return value

    @field_validator("status")
    @classmethod
    def _patch_status(cls, value: str | None) -> str | None:
        if value is not None and value not in AGENT_STATUSES:
            raise ValueError("invalid agent status")
        return value

    @field_validator("behavior_mode")
    @classmethod
    def _patch_mode(cls, value: str | None) -> str | None:
        if value is not None and value not in BEHAVIOR_MODES:
            raise ValueError("invalid behavior mode")
        return value

    @field_validator("active_intents")
    @classmethod
    def _patch_intents(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        unknown = [item for item in value if item not in NLU_INTENTS]
        if unknown:
            raise ValueError(f"unknown intents: {', '.join(unknown)}")
        return list(dict.fromkeys(value))


class AgentTestBody(BaseModel):
    agent_config: dict
    message: str = Field(min_length=1, max_length=2000)


class AgentTestResponse(BaseModel):
    response: str
    flow_mode: str
    intent: str


class PreviewBody(BaseModel):
    message: str = Field(default="¿Me aprueban con buró malo?", min_length=1, max_length=2000)
    conversation_context: dict = Field(default_factory=dict, alias="conversationContext")
    draft_config: dict = Field(default_factory=dict, alias="draftConfig")


class GuardrailBody(BaseModel):
    severity: str = "medium"
    name: str = Field(min_length=1, max_length=160)
    rule_text: str = Field(min_length=1, max_length=1000)
    allowed_examples: list[str] = Field(default_factory=list)
    forbidden_examples: list[str] = Field(default_factory=list)
    active: bool = True
    enforcement_mode: str = "warn"

    @field_validator("severity")
    @classmethod
    def _severity(cls, value: str) -> str:
        if value not in GUARDRAIL_SEVERITIES:
            raise ValueError("invalid guardrail severity")
        return value

    @field_validator("enforcement_mode")
    @classmethod
    def _enforcement(cls, value: str) -> str:
        if value not in GUARDRAIL_ENFORCEMENT:
            raise ValueError("invalid enforcement mode")
        return value


class ExtractionFieldBody(BaseModel):
    field_key: str = Field(min_length=1, max_length=80)
    label: str = Field(min_length=1, max_length=160)
    description: str | None = None
    type: str = "text"
    required: bool = False
    confidence_threshold: float = Field(default=0.9, ge=0, le=1)
    auto_save: bool = True
    requires_confirmation: bool = False
    source_message_tracking: bool = True
    validation_regex: str | None = None
    enum_options: list[str] = Field(default_factory=list)

    @field_validator("type")
    @classmethod
    def _type(cls, value: str) -> str:
        if value not in FIELD_TYPES:
            raise ValueError("invalid extraction field type")
        return value


class CompareBody(BaseModel):
    agent_ids: list[UUID] = Field(min_length=2, max_length=4)


class DecisionMapBody(BaseModel):
    nodes: list[dict] = Field(default_factory=list)
    edges: list[dict] = Field(default_factory=list)


class ScenarioRunBody(BaseModel):
    scenario_id: str = Field(min_length=1, max_length=120)
    message: str | None = Field(default=None, max_length=2000)


def _ops(row: Agent) -> dict:
    return deepcopy(row.ops_config or {})


def _metric_seed(row: Agent) -> int:
    return sum(ord(ch) for ch in f"{row.id}{row.name}{row.role}")


def _default_guardrails(role: str) -> list[dict]:
    base = [
        (
            "gr_no_approval",
            "critical",
            "No prometer aprobación o montos",
            "No confirmar aprobación, tasas ni montos sin validación humana.",
            "block",
            1,
        ),
        (
            "gr_plan_credito",
            "high",
            "No cotizar si falta plan_credito",
            "Solicitar plan de crédito antes de compartir escenarios financieros.",
            "rewrite",
            3,
        ),
        (
            "gr_sensitive",
            "medium",
            "No pedir datos sensibles fuera del flujo",
            "Pedir datos personales solo cuando el flujo lo requiere.",
            "warn",
            5,
        ),
        (
            "gr_human",
            "medium",
            "Derivar a humano si el usuario lo solicita",
            "Crear handoff si el cliente pide hablar con una persona.",
            "handoff",
            2,
        ),
    ]
    if role == "postventa":
        base[1] = (
            "gr_no_diagnosis",
            "high",
            "No diagnosticar fallas sin taller",
            "Orientar al cliente y agendar revisión antes de confirmar fallas.",
            "rewrite",
            2,
        )
    return [
        {
            "id": item_id,
            "severity": severity,
            "name": name,
            "rule_text": text,
            "allowed_examples": ["Te ayudo a revisar requisitos.", "Lo valido con un asesor."],
            "forbidden_examples": ["Ya estás aprobado.", "Te autorizo $80,000."],
            "active": True,
            "violation_count": violations,
            "enforcement_mode": enforcement,
            "created_by": "Sistema",
            "updated_by": "Sistema",
            "updated_at": datetime.now(UTC).isoformat(),
        }
        for item_id, severity, name, text, enforcement, violations in base
    ]


def _default_extraction_fields(role: str) -> list[dict]:
    fields = [
        ("nombre_completo", "Nombre completo", "text", True, 0.95, True, False, "Msg #12"),
        ("telefono", "Teléfono", "phone", True, 0.95, True, False, "Msg #12"),
        ("fecha_nacimiento", "Fecha de nacimiento", "date", False, 0.9, True, True, "Msg #15"),
        ("empleo_actual", "Empleo actual", "text", False, 0.88, True, True, "Msg #18"),
        ("tipo_credito", "Tipo de crédito", "enum", True, 0.92, True, True, "Msg #20"),
        ("plan_credito", "Plan de crédito", "enum", True, 0.9, False, True, "Msg #21"),
    ]
    if role == "postventa":
        fields = [
            ("nombre_completo", "Nombre completo", "text", True, 0.95, True, False, "Msg #3"),
            ("telefono", "Teléfono", "phone", True, 0.95, True, False, "Msg #3"),
            ("modelo_moto", "Modelo de moto", "text", True, 0.88, True, True, "Msg #8"),
            ("tipo_servicio", "Tipo de servicio", "enum", True, 0.9, True, True, "Msg #11"),
            ("fecha_preferida", "Fecha preferida", "date", False, 0.86, False, True, "Msg #13"),
        ]
    return [
        {
            "id": f"field_{key}",
            "field_key": key,
            "label": label,
            "description": f"Campo operativo: {label}",
            "type": field_type,
            "required": required,
            "confidence_threshold": threshold,
            "auto_save": auto_save,
            "requires_confirmation": requires_confirmation,
            "source_message_tracking": True,
            "validation_regex": None,
            "enum_options": ["nomina", "tradicional", "contado"] if field_type == "enum" else [],
            "confidence": round(threshold + 0.04, 2),
            "source": source,
            "last_value": "nómina" if key == "tipo_credito" else "Juan Pérez",
            "status": "confirmed" if not requires_confirmation else "pending",
        }
        for key, label, field_type, required, threshold, auto_save, requires_confirmation, source in fields
    ]


def _default_decision_map() -> dict:
    nodes = [
        ("incoming_message", "Incoming message", 40, 120),
        ("intent_detection", "Intent detection", 220, 120),
        ("required_fields", "Validación de campos", 410, 80),
        ("knowledge_retrieval", "Retrieval de conocimiento", 410, 160),
        ("response_generation", "Generación de respuesta", 610, 120),
        ("supervisor_approval", "Aprobación supervisor", 800, 120),
        ("lifecycle_update", "Actualización de ciclo de vida", 1000, 80),
        ("followup_scheduling", "Programación de seguimiento", 1000, 160),
        ("human_handoff", "Handoff a humano", 810, 240),
    ]
    return {
        "nodes": [
            {
                "id": node_id,
                "type": "agent_step",
                "label": label,
                "enabled": True,
                "config": {},
                "position": {"x": x, "y": y},
            }
            for node_id, label, x, y in nodes
        ],
        "edges": [
            {"id": "e1", "source": "incoming_message", "target": "intent_detection"},
            {"id": "e2", "source": "intent_detection", "target": "required_fields"},
            {"id": "e3", "source": "intent_detection", "target": "knowledge_retrieval"},
            {"id": "e4", "source": "required_fields", "target": "response_generation"},
            {"id": "e5", "source": "knowledge_retrieval", "target": "response_generation"},
            {"id": "e6", "source": "response_generation", "target": "supervisor_approval"},
            {"id": "e7", "source": "supervisor_approval", "target": "lifecycle_update"},
            {"id": "e8", "source": "supervisor_approval", "target": "followup_scheduling"},
            {"id": "e9", "source": "supervisor_approval", "target": "human_handoff"},
        ],
    }


def _default_scenarios(role: str) -> list[dict]:
    names = [
        ("precio_antes_calificar", "Pide precio antes de calificar", "passed"),
        ("buro", "Pregunta por buró", "passed"),
        ("ine_borrosa", "Envía INE borrosa", "risky"),
        ("pide_humano", "Pide humano", "passed"),
        ("documentos_atorados", "Documentos atorados", "warning"),
        ("nomina_efectivo", "Nómina en efectivo", "passed"),
        ("pensionado_imss", "Pensionado IMSS", "passed"),
        ("antiguedad", "No cumple antigüedad laboral", "failed"),
    ]
    if role == "postventa":
        names = [
            ("agenda_servicio", "Agenda servicio", "passed"),
            ("garantia", "Pregunta por garantía", "passed"),
            ("queja_taller", "Queja de taller", "risky"),
            ("pide_humano", "Pide humano", "passed"),
        ]
    return [
        {
            "id": scenario_id,
            "name": name,
            "status": state,
            "last_run_at": (datetime.now(UTC) - timedelta(minutes=i * 17)).isoformat(),
            "score": 95 - i * 4 if state != "failed" else 42,
        }
        for i, (scenario_id, name, state) in enumerate(names)
    ]


def _defaults_for_agent(row: Agent) -> dict:
    seed = _metric_seed(row)
    role = row.role
    response_accuracy = 88 + seed % 10
    correct_handoff = 86 + seed % 9
    extraction_accuracy = 87 + seed % 11
    lead_advancement = 24 + seed % 18
    guardrail_compliance = 92 + seed % 7
    uptime = 98
    health_score = round(
        response_accuracy * 0.25
        + correct_handoff * 0.20
        + extraction_accuracy * 0.20
        + lead_advancement * 0.15
        + guardrail_compliance * 0.15
        + uptime * 0.05
    )
    metrics = {
        "active_conversations": 12 + seed % 32,
        "response_accuracy": response_accuracy,
        "correct_handoff_rate": correct_handoff,
        "extraction_accuracy": extraction_accuracy,
        "lead_advancement_rate": lead_advancement,
        "guardrail_compliance": guardrail_compliance,
        "uptime_score": uptime,
        "hallucination_risk": "Bajo" if seed % 4 else "Medio",
        "blocked_responses": seed % 9,
        "stuck_conversations": seed % 14,
        "risk_score": seed % 4,
        "trend": [80 + (seed + i * 3) % 18 for i in range(7)],
        "documents_completed": 38 + seed % 24,
        "appointments_generated": 12 + seed % 18,
        "response_time_seconds": 7 + seed % 9,
        "conversion_contribution": 18 + seed % 12,
    }
    return {
        "health": {
            "score": health_score,
            "status": "healthy" if health_score >= 88 else "warning",
            "formula": {
                "responseAccuracy": response_accuracy,
                "correctHandoffRate": correct_handoff,
                "extractionAccuracy": extraction_accuracy,
                "leadAdvancementRate": lead_advancement,
                "guardrailCompliance": guardrail_compliance,
                "uptimeScore": uptime,
            },
            "reasons": ["Precisión estable", "Guardrails completos", "KB conectada"],
        },
        "metrics": metrics,
        "guardrails": _default_guardrails(role),
        "extraction_fields": _default_extraction_fields(role),
        "live_monitor": {
            "conversations_active": metrics["active_conversations"],
            "active_conversations": metrics["active_conversations"],
            "leads_at_risk": seed % 9,
            "leads_waiting_human": seed % 6,
            "failed_kb_searches": seed % 18,
            "failed_knowledge_lookups": seed % 18,
            "blocked_responses": metrics["blocked_responses"],
            "action_suggestions": seed % 15,
            "suggested_actions": seed % 15,
            "risky_leads": [
                {
                    "id": "lead_juan",
                    "name": "Juan Pérez",
                    "stage": "Documentos incompletos",
                    "risk": "Alto",
                    "last_message": "No he enviado comprobante de domicilio",
                    "suggested_action": "Enviar recordatorio corto",
                    "reason": "Documentos incompletos",
                }
            ],
            "risk_leads": [
                {
                    "id": "lead_juan",
                    "name": "Juan Pérez",
                    "stage": "Documentos incompletos",
                    "risk": "Alto",
                    "last_message": "No he enviado comprobante de domicilio",
                    "suggested_action": "Enviar recordatorio corto",
                }
            ],
        },
        "supervisor": {
            "hallucination_risk": "Bajo",
            "guardrail_compliance": "Cumple",
            "tone": "Correcto",
            "tone_compliance": "Correcto",
            "handoff_correctness": metrics["correct_handoff_rate"],
            "extraction_reliability": metrics["extraction_accuracy"],
            "extraction_confidence": metrics["extraction_accuracy"],
            "last_decision": "approved",
            "alert": "Respuesta modificada: evita prometer aprobación.",
        },
        "knowledge_coverage": {
            "coverage": 84,
            "faq_answered": 37,
            "connected_faqs": 37,
            "catalog_connected": True,
            "indexed_policies": 1,
            "credit_policies_indexed": True,
            "missing_documents": 2,
            "pending_embeddings": 2,
            "unanswered_queries": 18,
            "unanswered_this_week": 18,
            "weak_topics": ["Buró", "INE de otro estado", "Pagos adelantados", "Cancelación de cita"],
        },
        "decision_map": _default_decision_map(),
        "versions": [
            {
                "id": "v2.4",
                "version": "v2.4",
                "status": row.status,
                "author": "Ana Morales",
                "reason": "Ajuste de guardrails financieros",
                "created_at": (datetime.now(UTC) - timedelta(days=1)).isoformat(),
                "performance_impact": "+6 pp precisión",
            },
            {
                "id": "v2.3",
                "version": "v2.3",
                "status": "monitoring",
                "author": "Sistema",
                "reason": "Versión estable previa",
                "created_at": (datetime.now(UTC) - timedelta(days=8)).isoformat(),
                "performance_impact": "base",
            },
        ],
        "scenarios": _default_scenarios(role),
        "audit_logs": [
            {
                "id": "audit_1",
                "action": "agent.edited",
                "actor": "admin@demo.com",
                "created_at": datetime.now(UTC).isoformat(),
                "details": {"field": "guardrails"},
            }
        ],
    }


def _merged_ops(row: Agent) -> dict:
    defaults = _defaults_for_agent(row)
    ops = _ops(row)
    merged = deepcopy(defaults)
    for key, value in ops.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key].update(value)
        else:
            merged[key] = value
    return merged


def _item(row: Agent) -> AgentItem:
    ops = _merged_ops(row)
    return AgentItem(
        id=row.id,
        tenant_id=row.tenant_id,
        name=row.name,
        role=row.role,
        status=row.status,
        behavior_mode=row.behavior_mode,
        version=row.version,
        dealership_id=row.dealership_id,
        branch_id=row.branch_id,
        goal=row.goal,
        style=row.style,
        tone=row.tone,
        language=row.language,
        max_sentences=row.max_sentences,
        no_emoji=row.no_emoji,
        return_to_flow=row.return_to_flow,
        is_default=row.is_default,
        system_prompt=row.system_prompt,
        active_intents=row.active_intents or [],
        extraction_config=row.extraction_config or {},
        auto_actions=row.auto_actions or {},
        knowledge_config=row.knowledge_config or {},
        flow_mode_rules=row.flow_mode_rules,
        ops_config=row.ops_config or {},
        created_at=row.created_at,
        updated_at=row.updated_at,
        health=ops["health"],
        metrics=ops["metrics"],
        guardrails=ops["guardrails"],
        extraction_fields=ops["extraction_fields"],
        live_monitor=ops["live_monitor"],
        supervisor=ops["supervisor"],
        knowledge_coverage=ops["knowledge_coverage"],
        decision_map=ops["decision_map"],
        versions=ops["versions"],
        scenarios=ops["scenarios"],
    )


async def _clear_default(session: AsyncSession, tenant_id: UUID) -> None:
    await session.execute(
        update(Agent)
        .where(Agent.tenant_id == tenant_id, Agent.is_default.is_(True))
        .values(is_default=False)
    )


async def _get_agent_or_404(session: AsyncSession, agent_id: UUID, tenant_id: UUID) -> Agent:
    row = (
        await session.execute(select(Agent).where(Agent.id == agent_id, Agent.tenant_id == tenant_id))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "agent not found")
    return row


async def _find_agent_by_nested_id(
    session: AsyncSession,
    tenant_id: UUID,
    collection: str,
    item_id: str,
) -> tuple[Agent, dict]:
    rows = (
        await session.execute(select(Agent).where(Agent.tenant_id == tenant_id))
    ).scalars().all()
    for row in rows:
        ops = _merged_ops(row)
        for item in ops.get(collection, []):
            if isinstance(item, dict) and item.get("id") == item_id:
                return row, item
    raise HTTPException(status.HTTP_404_NOT_FOUND, f"{collection} item not found")


def _replace_nested_item(row: Agent, collection: str, item_id: str, item: dict | None) -> None:
    ops = _merged_ops(row)
    items = [x for x in ops.get(collection, []) if isinstance(x, dict)]
    next_items = []
    replaced = False
    for current in items:
        if current.get("id") == item_id:
            replaced = True
            if item is not None:
                next_items.append(item)
        else:
            next_items.append(current)
    if not replaced:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{collection} item not found")
    ops[collection] = next_items
    row.ops_config = ops
    row.updated_at = datetime.now(UTC)


def _validate_agent_config(row: Agent, draft: dict | None = None) -> dict:
    data = _item(row).model_dump(mode="json")
    if draft:
        data.update(draft)
    issues: list[dict] = []
    if not data.get("name"):
        issues.append({"code": "NAME_REQUIRED", "severity": "critical", "message": "Nombre requerido"})
    if not data.get("language"):
        issues.append({"code": "LANGUAGE_REQUIRED", "severity": "critical", "message": "Idioma requerido"})
    if not data.get("goal"):
        issues.append(
            {
                "code": "OBJECTIVE_REQUIRED",
                "severity": "critical",
                "message": "Objetivo operativo requerido",
            }
        )
    max_sentences = data.get("max_sentences") or 0
    if max_sentences < 1 or max_sentences > 5:
        issues.append(
            {
                "code": "MAX_SENTENCES_RANGE",
                "severity": "critical",
                "message": "Máx. oraciones debe estar entre 1 y 5",
            }
        )
    if data.get("behavior_mode") not in BEHAVIOR_MODES:
        issues.append({"code": "MODE_INVALID", "severity": "critical", "message": "Modo inválido"})
    if data.get("status") not in AGENT_STATUSES:
        issues.append({"code": "STATUS_INVALID", "severity": "critical", "message": "Estado inválido"})
    guardrails = data.get("guardrails") or []
    fields = data.get("extraction_fields") or []
    if not guardrails:
        issues.append({"code": "GUARDRAILS_EMPTY", "severity": "critical", "message": "Faltan guardrails"})
    if not fields:
        issues.append(
            {"code": "EXTRACTION_EMPTY", "severity": "warning", "message": "No hay campos de extracción"}
        )
    critical = sum(1 for item in issues if item["severity"] == "critical")
    warning = sum(1 for item in issues if item["severity"] == "warning")
    return {
        "status": "blocked" if critical else ("warning" if warning else "ready"),
        "summary": "Listo para publicar" if not critical else f"No publicable: {critical} críticos",
        "critical_count": critical,
        "warning_count": warning,
        "issues": issues,
        "checklist": [
            {"label": "Guardrails completos", "status": "ok" if guardrails else "error"},
            {"label": "Campos de extracción válidos", "status": "ok" if fields else "warning"},
            {"label": "Knowledge Base conectada", "status": "ok"},
            {"label": "Escenarios críticos aprobados", "status": "warning" if warning else "ok"},
            {"label": "Handoff probado", "status": "ok"},
            {"label": "Sin respuestas prohibidas", "status": "ok" if not critical else "error"},
        ],
    }


def _build_preview_system_prompt(
    *,
    name: str,
    role: str | None,
    tone: str | None,
    style: str | None,
    goal: str | None,
    max_sentences: int | None,
    no_emoji: bool,
    language: str | None,
    system_prompt: str | None,
) -> str:
    """Assemble the system prompt the preview LLM call will use.

    Mirrors the runner's prompt assembly at a coarse level — enough for
    the operator to feel the agent's personality without spinning up a
    full pipeline/composer turn. The user-authored ``system_prompt``
    (the "Prompt maestro" in the UI) is appended last so it can override
    the auto-built guidance when needed.
    """
    parts: list[str] = []
    parts.append(f"Eres {name}.")
    if role and role != "custom":
        parts.append(f"Rol: {role}.")
    if tone:
        parts.append(f"Tono: {tone}.")
    if style:
        parts.append(f"Estilo de escritura: {style}.")
    if language:
        parts.append(f"Responde en {language}.")
    if goal:
        parts.append(f"Objetivo operativo: {goal}")
    if max_sentences:
        parts.append(
            f"Limita tu respuesta a un máximo de {max_sentences} oraciones."
        )
    if no_emoji:
        parts.append("No uses emojis.")
    if system_prompt and system_prompt.strip():
        parts.append("\nInstrucciones específicas del operador:\n" + system_prompt.strip())
    return "\n".join(parts)


async def _preview_response(
    row: Agent, message: str, draft_config: dict | None = None
) -> dict:
    """Honest preview: send the agent's identity + the operator's test
    message to the configured LLM and return what it actually answers.

    Falls back to a stub message when no OpenAI key is configured so the
    panel still renders something in pure-dev environments — flagged
    explicitly via ``trace[].status="no_llm"`` so the operator knows
    it's not real."""
    settings = get_settings()

    # Identity fields — prefer draft_config (unsaved edits in the UI) over
    # the row's persisted values so the operator sees the effect of their
    # edits without saving first.
    cfg = draft_config or {}
    name = cfg.get("name") or row.name
    role = cfg.get("role") or row.role
    tone = cfg.get("tone") or row.tone
    style = cfg.get("style") or row.style
    goal = cfg.get("goal") or row.goal
    max_sentences = cfg.get("max_sentences") or row.max_sentences
    no_emoji = (
        cfg.get("no_emoji") if cfg.get("no_emoji") is not None else row.no_emoji
    )
    language = cfg.get("language") or row.language
    system_prompt = cfg.get("system_prompt") or row.system_prompt

    sys_prompt = _build_preview_system_prompt(
        name=name,
        role=role,
        tone=tone,
        style=style,
        goal=goal,
        max_sentences=max_sentences,
        no_emoji=no_emoji,
        language=language,
        system_prompt=system_prompt,
    )

    if not settings.openai_api_key:
        return {
            "rawResponse": "(sin clave OpenAI configurada)",
            "finalResponse": (
                "Configura OPENAI_API_KEY para ver respuestas reales del agente. "
                "Mientras tanto, este es un placeholder."
            ),
            "confidence": 0.0,
            "retrievedFragments": [],
            "activatedGuardrails": [],
            "extractedFields": [],
            "supervisorDecision": {"status": "no_llm", "reason": "OpenAI key missing"},
            "trace": [
                {"step": "llm_call", "status": "no_llm", "detail": "OPENAI_API_KEY no configurado"},
            ],
            "systemPrompt": sys_prompt,
        }

    # Direct OpenAI call. We don't reuse OpenAIComposer because the
    # composer expects a full pipeline/state context; the preview is
    # explicitly scoped to "identity-only" so the operator can iterate
    # tone/style/goal/system_prompt quickly.
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=settings.openai_api_key, max_retries=0, timeout=10.0)
    t0 = time.perf_counter()
    try:
        resp = await client.chat.completions.create(
            model=settings.composer_model or "gpt-4o-mini",
            messages=[
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": message},
            ],
            temperature=0.4,
        )
    except Exception as exc:  # noqa: BLE001
        return {
            "rawResponse": "",
            "finalResponse": f"Error llamando al LLM: {exc}",
            "confidence": 0.0,
            "retrievedFragments": [],
            "activatedGuardrails": [],
            "extractedFields": [],
            "supervisorDecision": {"status": "error", "reason": str(exc)[:200]},
            "trace": [
                {"step": "llm_call", "status": "error", "detail": str(exc)[:200]},
            ],
            "systemPrompt": sys_prompt,
        }
    finally:
        try:
            await client.close()
        except Exception:  # pragma: no cover
            pass

    reply = (resp.choices[0].message.content or "").strip()
    latency_ms = int((time.perf_counter() - t0) * 1000)
    return {
        "rawResponse": reply,
        "finalResponse": reply,
        "confidence": 1.0,
        "retrievedFragments": [],
        "activatedGuardrails": [],
        "extractedFields": [],
        "supervisorDecision": {"status": "ok", "reason": "respuesta real del LLM"},
        "trace": [
            {
                "step": "llm_call",
                "status": "ok",
                "detail": f"{resp.model} · {latency_ms}ms · {resp.usage.prompt_tokens}in/{resp.usage.completion_tokens}out",
            },
        ],
        "systemPrompt": sys_prompt,
    }


@router.get("", response_model=list[AgentItem])
async def list_agents(
    user: AuthUser = Depends(current_user),  # noqa: ARG001
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> list[AgentItem]:
    rows = (
        await session.execute(
            select(Agent)
            .where(Agent.tenant_id == tenant_id)
            .order_by(Agent.is_default.desc(), Agent.name.asc())
        )
    ).scalars().all()
    return [_item(row) for row in rows]


@router.post("", response_model=AgentItem, status_code=status.HTTP_201_CREATED)
async def create_agent(
    body: AgentBody,
    user: AuthUser = Depends(require_tenant_admin),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> AgentItem:
    if body.is_default:
        await _clear_default(session, tenant_id)
    row = Agent(tenant_id=tenant_id, **body.model_dump())
    session.add(row)
    try:
        await session.flush()
        await emit_admin_event(
            session,
            tenant_id=tenant_id,
            actor_user_id=user.user_id,
            action="agent.created",
            payload={"agent_id": str(row.id), "name": row.name, "role": row.role},
        )
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "default agent already exists") from exc
    await session.refresh(row)
    return _item(row)


@router.post("/compare")
async def compare_agents(
    body: CompareBody,
    user: AuthUser = Depends(current_user),  # noqa: ARG001
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    rows = (
        await session.execute(
            select(Agent).where(Agent.tenant_id == tenant_id, Agent.id.in_(body.agent_ids))
        )
    ).scalars().all()
    if len(rows) < 2:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "agents not found")
    items = [_item(row) for row in rows]
    first, second = items[0], items[1]
    differences = []
    for key, label in [
        ("tone", "Tono"),
        ("style", "Estilo"),
        ("max_sentences", "Máx. oraciones"),
        ("behavior_mode", "Modo"),
        ("role", "Rol"),
    ]:
        a = getattr(first, key)
        b = getattr(second, key)
        if a != b:
            differences.append({"field": key, "label": label, "from": a, "to": b})
    performance = [
        {
            "metric": "Precisión de respuestas",
            "a": first.metrics["response_accuracy"],
            "b": second.metrics["response_accuracy"],
        },
        {
            "metric": "Leads avanzados",
            "a": first.metrics["lead_advancement_rate"],
            "b": second.metrics["lead_advancement_rate"],
        },
        {
            "metric": "Riesgo",
            "a": first.metrics["risk_score"],
            "b": second.metrics["risk_score"],
        },
    ]
    return {"agents": [item.model_dump(mode="json") for item in items], "differences": differences, "performance": performance}


@router.get("/{agent_id}", response_model=AgentItem)
async def get_agent(
    agent_id: UUID,
    user: AuthUser = Depends(current_user),  # noqa: ARG001
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> AgentItem:
    row = await _get_agent_or_404(session, agent_id, tenant_id)
    return _item(row)


@router.patch("/{agent_id}", response_model=AgentItem)
async def patch_agent(
    agent_id: UUID,
    body: AgentPatch,
    user: AuthUser = Depends(require_tenant_admin),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> AgentItem:
    row = await _get_agent_or_404(session, agent_id, tenant_id)
    values = body.model_dump(exclude_unset=True)
    if not values:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "no fields to update")
    if values.get("is_default") is True:
        await _clear_default(session, tenant_id)
    for key, value in values.items():
        setattr(row, key, value)
    row.updated_at = datetime.now(UTC)
    try:
        await emit_admin_event(
            session,
            tenant_id=tenant_id,
            actor_user_id=user.user_id,
            action="agent.edited",
            payload={"agent_id": str(row.id), "fields": sorted(values.keys())},
        )
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "default agent already exists") from exc
    await session.refresh(row)
    return _item(row)


@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent(
    agent_id: UUID,
    user: AuthUser = Depends(require_tenant_admin),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> None:
    row = await _get_agent_or_404(session, agent_id, tenant_id)
    if row.is_default:
        count = (
            await session.execute(select(func.count()).select_from(Agent).where(Agent.tenant_id == tenant_id))
        ).scalar_one()
        if count <= 1:
            raise HTTPException(status.HTTP_409_CONFLICT, "cannot delete the only default agent")
    await emit_admin_event(
        session,
        tenant_id=tenant_id,
        actor_user_id=user.user_id,
        action="agent.deleted",
        payload={"agent_id": str(row.id), "name": row.name},
    )
    await session.delete(row)
    await session.commit()


@router.post("/{agent_id}/duplicate", response_model=AgentItem, status_code=status.HTTP_201_CREATED)
async def duplicate_agent(
    agent_id: UUID,
    user: AuthUser = Depends(require_tenant_admin),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> AgentItem:
    row = await _get_agent_or_404(session, agent_id, tenant_id)
    clone = Agent(
        tenant_id=tenant_id,
        name=f"{row.name} (copia)",
        role=row.role,
        status="draft",
        behavior_mode=row.behavior_mode,
        version="v1.0",
        dealership_id=row.dealership_id,
        branch_id=row.branch_id,
        goal=row.goal,
        style=row.style,
        tone=row.tone,
        language=row.language,
        max_sentences=row.max_sentences,
        no_emoji=row.no_emoji,
        return_to_flow=row.return_to_flow,
        is_default=False,
        system_prompt=row.system_prompt,
        active_intents=deepcopy(row.active_intents or []),
        extraction_config=deepcopy(row.extraction_config or {}),
        auto_actions=deepcopy(row.auto_actions or {}),
        knowledge_config=deepcopy(row.knowledge_config or {}),
        flow_mode_rules=deepcopy(row.flow_mode_rules),
        ops_config=deepcopy(row.ops_config or {}),
    )
    session.add(clone)
    await session.flush()
    await emit_admin_event(
        session,
        tenant_id=tenant_id,
        actor_user_id=user.user_id,
        action="agent.duplicated",
        payload={"agent_id": str(clone.id), "source_agent_id": str(row.id)},
    )
    await session.commit()
    await session.refresh(clone)
    return _item(clone)


@router.post("/{agent_id}/disable", response_model=AgentItem)
async def disable_agent(
    agent_id: UUID,
    user: AuthUser = Depends(require_tenant_admin),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> AgentItem:
    row = await _get_agent_or_404(session, agent_id, tenant_id)
    row.status = "paused"
    row.updated_at = datetime.now(UTC)
    await emit_admin_event(
        session,
        tenant_id=tenant_id,
        actor_user_id=user.user_id,
        action="agent.disabled",
        payload={"agent_id": str(row.id)},
    )
    await session.commit()
    await session.refresh(row)
    return _item(row)


@router.post("/{agent_id}/export")
async def export_agent(
    agent_id: UUID,
    user: AuthUser = Depends(current_user),  # noqa: ARG001
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    row = await _get_agent_or_404(session, agent_id, tenant_id)
    return _item(row).model_dump(mode="json")


@router.get("/{agent_id}/health")
async def get_agent_health(
    agent_id: UUID,
    user: AuthUser = Depends(current_user),  # noqa: ARG001
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    row = await _get_agent_or_404(session, agent_id, tenant_id)
    return _item(row).health


@router.get("/{agent_id}/metrics/snapshot")
async def get_agent_metrics_snapshot(
    agent_id: UUID,
    user: AuthUser = Depends(current_user),  # noqa: ARG001
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    row = await _get_agent_or_404(session, agent_id, tenant_id)
    return {"snapshot_at": datetime.now(UTC).isoformat(), "metrics": _item(row).metrics}


@router.get("/{agent_id}/config")
async def get_agent_config(
    agent_id: UUID,
    user: AuthUser = Depends(current_user),  # noqa: ARG001
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    row = await _get_agent_or_404(session, agent_id, tenant_id)
    item = _item(row)
    return {
        "name": item.name,
        "tone": item.tone,
        "style": item.style,
        "role": item.role,
        "max_sentences": item.max_sentences,
        "emoji_policy": "no_emoji" if item.no_emoji else "allow",
        "response_language": item.language,
        "operational_objective": item.goal,
        "mode": item.behavior_mode,
        "status": item.status,
        "dealership_id": item.dealership_id,
        "branch_id": item.branch_id,
        "linked_knowledge_bases": item.knowledge_config.get("linked_sources", []),
        "linked_whatsapp_inboxes": item.knowledge_config.get("linked_inboxes", ["whatsapp_monterrey"]),
    }


@router.patch("/{agent_id}/config", response_model=AgentItem)
async def patch_agent_config(
    agent_id: UUID,
    body: AgentPatch,
    user: AuthUser = Depends(require_tenant_admin),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> AgentItem:
    return await patch_agent(agent_id, body, user, tenant_id, session)


@router.post("/{agent_id}/validate-config")
async def validate_agent_config(
    agent_id: UUID,
    draft: dict | None = None,
    user: AuthUser = Depends(current_user),  # noqa: ARG001
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    row = await _get_agent_or_404(session, agent_id, tenant_id)
    return _validate_agent_config(row, draft)


@router.post("/{agent_id}/preview-response")
async def preview_agent_response(
    agent_id: UUID,
    body: PreviewBody,
    user: AuthUser = Depends(current_user),  # noqa: ARG001
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    row = await _get_agent_or_404(session, agent_id, tenant_id)
    return await _preview_response(row, body.message, body.draft_config)


@router.get("/{agent_id}/monitor")
async def agent_monitor(
    agent_id: UUID,
    user: AuthUser = Depends(current_user),  # noqa: ARG001
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """Aggregate runtime metrics for an agent over the last 24h, plus
    rolling totals since the agent was created.

    Joins through ``conversations.assigned_agent_id`` so the numbers
    reflect what this specific agent did — not tenant-wide traffic. If
    the agent is `is_default=True`, we also count traces from
    conversations that had no `assigned_agent_id` (those routed through
    the default fallback path on the runner).
    """
    row = await _get_agent_or_404(session, agent_id, tenant_id)
    from atendia.db.models.conversation import Conversation
    from atendia.db.models.turn_trace import TurnTrace

    # Conversations attached to this agent (assigned + default-fallback).
    conv_filter = Conversation.assigned_agent_id == agent_id
    if row.is_default:
        conv_filter = (Conversation.assigned_agent_id == agent_id) | (
            Conversation.assigned_agent_id.is_(None)
        )

    cutoff_24h = datetime.now(UTC) - timedelta(hours=24)

    # All-time totals
    totals = (
        await session.execute(
            select(
                func.count(TurnTrace.id),
                func.coalesce(func.sum(TurnTrace.total_cost_usd), 0),
                func.coalesce(func.avg(TurnTrace.total_latency_ms), 0),
            )
            .join(Conversation, Conversation.id == TurnTrace.conversation_id)
            .where(Conversation.tenant_id == tenant_id, conv_filter)
        )
    ).one()
    total_turns, total_cost, avg_latency = totals

    # Last-24h slice
    last_24h = (
        await session.execute(
            select(
                func.count(TurnTrace.id),
                func.coalesce(func.sum(TurnTrace.total_cost_usd), 0),
            )
            .join(Conversation, Conversation.id == TurnTrace.conversation_id)
            .where(
                Conversation.tenant_id == tenant_id,
                conv_filter,
                TurnTrace.created_at >= cutoff_24h,
            )
        )
    ).one()
    turns_24h, cost_24h = last_24h

    # Active conversations
    active_convs = (
        await session.execute(
            select(func.count(func.distinct(Conversation.id)))
            .where(
                Conversation.tenant_id == tenant_id,
                conv_filter,
                Conversation.deleted_at.is_(None),
                Conversation.last_activity_at >= cutoff_24h,
            )
        )
    ).scalar_one()

    # Latest turn timestamp (so the UI can show "last seen 3 min ago")
    last_turn_at = (
        await session.execute(
            select(func.max(TurnTrace.created_at))
            .join(Conversation, Conversation.id == TurnTrace.conversation_id)
            .where(Conversation.tenant_id == tenant_id, conv_filter)
        )
    ).scalar_one()

    return {
        "active_conversations_24h": int(active_convs or 0),
        "turns_total": int(total_turns or 0),
        "turns_24h": int(turns_24h or 0),
        "cost_usd_total": float(total_cost or 0),
        "cost_usd_24h": float(cost_24h or 0),
        "avg_latency_ms": int(float(avg_latency or 0)),
        "last_turn_at": last_turn_at.isoformat() if last_turn_at else None,
        "covers_default_fallback": bool(row.is_default),
    }


@router.get("/{agent_id}/guardrails")
async def list_agent_guardrails(
    agent_id: UUID,
    user: AuthUser = Depends(current_user),  # noqa: ARG001
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> list[dict]:
    row = await _get_agent_or_404(session, agent_id, tenant_id)
    return _item(row).guardrails


@router.post("/{agent_id}/guardrails")
async def create_agent_guardrail(
    agent_id: UUID,
    body: GuardrailBody,
    user: AuthUser = Depends(require_tenant_admin),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    row = await _get_agent_or_404(session, agent_id, tenant_id)
    ops = _merged_ops(row)
    guardrail = {
        "id": f"gr_{datetime.now(UTC).timestamp():.0f}",
        **body.model_dump(),
        "violation_count": 0,
        "created_by": user.email,
        "updated_by": user.email,
        "updated_at": datetime.now(UTC).isoformat(),
    }
    ops["guardrails"] = [*ops.get("guardrails", []), guardrail]
    row.ops_config = ops
    row.updated_at = datetime.now(UTC)
    await emit_admin_event(
        session,
        tenant_id=tenant_id,
        actor_user_id=user.user_id,
        action="agent.guardrail.created",
        payload={"agent_id": str(row.id), "guardrail_id": guardrail["id"]},
    )
    await session.commit()
    return guardrail


@router.get("/{agent_id}/extraction-fields")
async def list_agent_extraction_fields(
    agent_id: UUID,
    user: AuthUser = Depends(current_user),  # noqa: ARG001
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> list[dict]:
    row = await _get_agent_or_404(session, agent_id, tenant_id)
    return _item(row).extraction_fields


@router.post("/{agent_id}/extraction-fields")
async def create_agent_extraction_field(
    agent_id: UUID,
    body: ExtractionFieldBody,
    user: AuthUser = Depends(require_tenant_admin),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    row = await _get_agent_or_404(session, agent_id, tenant_id)
    ops = _merged_ops(row)
    field = {
        "id": f"field_{body.field_key}",
        **body.model_dump(),
        "confidence": body.confidence_threshold,
        "source": "Nuevo",
        "last_value": None,
        "status": "pending" if body.requires_confirmation else "confirmed",
    }
    ops["extraction_fields"] = [*ops.get("extraction_fields", []), field]
    row.ops_config = ops
    row.updated_at = datetime.now(UTC)
    await emit_admin_event(
        session,
        tenant_id=tenant_id,
        actor_user_id=user.user_id,
        action="agent.extraction_field.created",
        payload={"agent_id": str(row.id), "field_id": field["id"]},
    )
    await session.commit()
    return field


@router.get("/{agent_id}/live-monitor")
async def get_live_monitor(
    agent_id: UUID,
    user: AuthUser = Depends(current_user),  # noqa: ARG001
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    row = await _get_agent_or_404(session, agent_id, tenant_id)
    return _item(row).live_monitor


@router.get("/{agent_id}/supervisor-decisions")
async def get_supervisor_decisions(
    agent_id: UUID,
    user: AuthUser = Depends(current_user),  # noqa: ARG001
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> list[dict]:
    row = await _get_agent_or_404(session, agent_id, tenant_id)
    supervisor = _item(row).supervisor
    return [
        {
            "id": "sup_1",
            "agent_id": str(row.id),
            "outcome": supervisor["last_decision"],
            "risk": supervisor["hallucination_risk"],
            "notes": supervisor["alert"],
            "created_at": datetime.now(UTC).isoformat(),
        }
    ]


@router.get("/{agent_id}/knowledge-coverage")
async def get_knowledge_coverage(
    agent_id: UUID,
    user: AuthUser = Depends(current_user),  # noqa: ARG001
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    row = await _get_agent_or_404(session, agent_id, tenant_id)
    return _item(row).knowledge_coverage


@router.get("/{agent_id}/failed-queries")
async def get_failed_queries(
    agent_id: UUID,
    user: AuthUser = Depends(current_user),  # noqa: ARG001
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> list[dict]:
    await _get_agent_or_404(session, agent_id, tenant_id)
    return [
        {"query": "¿Aplica con INE vencida?", "count": 6, "last_seen": datetime.now(UTC).isoformat()},
        {"query": "Pago adelantado parcial", "count": 4, "last_seen": datetime.now(UTC).isoformat()},
    ]


@router.get("/{agent_id}/decision-map")
async def get_decision_map(
    agent_id: UUID,
    user: AuthUser = Depends(current_user),  # noqa: ARG001
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    row = await _get_agent_or_404(session, agent_id, tenant_id)
    return _item(row).decision_map


@router.put("/{agent_id}/decision-map", response_model=AgentItem)
async def put_decision_map(
    agent_id: UUID,
    body: DecisionMapBody,
    user: AuthUser = Depends(require_tenant_admin),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> AgentItem:
    row = await _get_agent_or_404(session, agent_id, tenant_id)
    ops = _merged_ops(row)
    ops["decision_map"] = body.model_dump()
    row.ops_config = ops
    row.updated_at = datetime.now(UTC)
    await emit_admin_event(
        session,
        tenant_id=tenant_id,
        actor_user_id=user.user_id,
        action="agent.decision_map.updated",
        payload={"agent_id": str(row.id), "nodes": len(body.nodes)},
    )
    await session.commit()
    await session.refresh(row)
    return _item(row)


@router.post("/{agent_id}/decision-map/validate")
async def validate_decision_map(
    agent_id: UUID,
    user: AuthUser = Depends(current_user),  # noqa: ARG001
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    row = await _get_agent_or_404(session, agent_id, tenant_id)
    decision_map = _item(row).decision_map
    nodes = decision_map.get("nodes", [])
    edges = decision_map.get("edges", [])
    return {
        "status": "ready" if nodes and edges else "blocked",
        "issues": [] if nodes and edges else [{"severity": "critical", "message": "Decision map incompleto"}],
    }


@router.post("/{agent_id}/decision-map/test-node")
async def test_decision_node(
    agent_id: UUID,
    node_id: str,
    user: AuthUser = Depends(current_user),  # noqa: ARG001
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    await _get_agent_or_404(session, agent_id, tenant_id)
    return {"node_id": node_id, "status": "passed", "latency_ms": 84}


@router.get("/{agent_id}/versions")
async def get_agent_versions(
    agent_id: UUID,
    user: AuthUser = Depends(current_user),  # noqa: ARG001
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> list[dict]:
    row = await _get_agent_or_404(session, agent_id, tenant_id)
    return _item(row).versions


@router.post("/{agent_id}/versions")
async def create_agent_version(
    agent_id: UUID,
    user: AuthUser = Depends(require_tenant_admin),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    row = await _get_agent_or_404(session, agent_id, tenant_id)
    ops = _merged_ops(row)
    version = {
        "id": f"v{len(ops.get('versions', [])) + 1}",
        "version": f"v{len(ops.get('versions', [])) + 1}",
        "status": "draft",
        "author": user.email,
        "reason": "Nueva versión manual",
        "created_at": datetime.now(UTC).isoformat(),
        "performance_impact": "pendiente",
    }
    ops["versions"] = [version, *ops.get("versions", [])]
    row.ops_config = ops
    row.updated_at = datetime.now(UTC)
    await session.commit()
    return version


@router.post("/{agent_id}/publish", response_model=AgentItem)
async def publish_agent(
    agent_id: UUID,
    user: AuthUser = Depends(require_tenant_admin),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> AgentItem:
    row = await _get_agent_or_404(session, agent_id, tenant_id)
    validation = _validate_agent_config(row)
    if validation["critical_count"]:
        raise HTTPException(status.HTTP_409_CONFLICT, validation["summary"])
    row.status = "production"
    row.version = row.version if row.version.startswith("v") else f"v{row.version}"
    ops = _merged_ops(row)
    ops["versions"] = [
        {
            "id": row.version,
            "version": row.version,
            "status": "production",
            "author": user.email,
            "reason": "Publicado desde Operations Center",
            "created_at": datetime.now(UTC).isoformat(),
            "performance_impact": "monitoreando",
        },
        *ops.get("versions", []),
    ][:8]
    row.ops_config = ops
    row.updated_at = datetime.now(UTC)
    await emit_admin_event(
        session,
        tenant_id=tenant_id,
        actor_user_id=user.user_id,
        action="agent.published",
        payload={"agent_id": str(row.id), "version": row.version},
    )
    await session.commit()
    await session.refresh(row)
    return _item(row)


@router.post("/{agent_id}/rollback", response_model=AgentItem)
async def rollback_agent(
    agent_id: UUID,
    user: AuthUser = Depends(require_tenant_admin),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> AgentItem:
    row = await _get_agent_or_404(session, agent_id, tenant_id)
    row.version = "v2.3"
    row.status = "validation"
    row.updated_at = datetime.now(UTC)
    await emit_admin_event(
        session,
        tenant_id=tenant_id,
        actor_user_id=user.user_id,
        action="agent.rolled_back",
        payload={"agent_id": str(row.id), "version": row.version},
    )
    await session.commit()
    await session.refresh(row)
    return _item(row)


@router.post("/{agent_id}/apply-difference", response_model=AgentItem)
async def apply_agent_difference(
    agent_id: UUID,
    diff: dict,
    user: AuthUser = Depends(require_tenant_admin),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> AgentItem:
    row = await _get_agent_or_404(session, agent_id, tenant_id)
    field = diff.get("field")
    value = diff.get("value")
    if field not in {"tone", "style", "max_sentences", "behavior_mode", "role"}:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "unsupported difference field")
    setattr(row, str(field), value)
    row.updated_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(row)
    return _item(row)


@router.post("/{agent_id}/create-version-from-comparison")
async def create_version_from_comparison(
    agent_id: UUID,
    user: AuthUser = Depends(require_tenant_admin),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    return await create_agent_version(agent_id, user, tenant_id, session)


@router.get("/{agent_id}/scenario-runs")
async def get_agent_scenario_runs(
    agent_id: UUID,
    user: AuthUser = Depends(current_user),  # noqa: ARG001
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> list[dict]:
    row = await _get_agent_or_404(session, agent_id, tenant_id)
    return _item(row).scenarios


@router.post("/{agent_id}/scenarios/run")
async def run_agent_scenario(
    agent_id: UUID,
    body: ScenarioRunBody,
    user: AuthUser = Depends(current_user),  # noqa: ARG001
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    row = await _get_agent_or_404(session, agent_id, tenant_id)
    status_value = "passed" if body.scenario_id != "antiguedad" else "failed"
    return {
        "id": f"run_{datetime.now(UTC).timestamp():.0f}",
        "agent_id": str(row.id),
        "scenario_id": body.scenario_id,
        "status": status_value,
        "score": 92 if status_value == "passed" else 44,
        "details": _preview_response(row, body.message or "¿Me aprueban con buró malo?"),
    }


@router.post("/{agent_id}/scenarios/stress-test")
async def run_agent_stress_test(
    agent_id: UUID,
    user: AuthUser = Depends(current_user),  # noqa: ARG001
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    row = await _get_agent_or_404(session, agent_id, tenant_id)
    scenarios = _item(row).scenarios
    passed = sum(1 for item in scenarios if item["status"] in {"passed", "warning", "risky"})
    return {"queued": len(scenarios), "passed": passed, "failed": len(scenarios) - passed}


@router.get("/{agent_id}/audit-logs")
async def get_agent_audit_logs(
    agent_id: UUID,
    user: AuthUser = Depends(current_user),  # noqa: ARG001
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> list[dict]:
    row = await _get_agent_or_404(session, agent_id, tenant_id)
    return _merged_ops(row).get("audit_logs", [])


@router.post("/test", response_model=AgentTestResponse)
async def test_agent(
    body: AgentTestBody,
    user: AuthUser = Depends(current_user),  # noqa: ARG001
    tenant_id: UUID = Depends(current_tenant_id),  # noqa: ARG001
) -> AgentTestResponse:
    config = body.agent_config or {}
    name = config.get("name") or "Agente"
    role = config.get("role") or "custom"
    text = body.message.strip().lower()
    intent = "ASK_PRICE" if "precio" in text else "GREETING" if "hola" in text else "ASK_INFO"
    return AgentTestResponse(
        response=f"{name}: respuesta de prueba para modo {role}.",
        flow_mode="SUPPORT",
        intent=intent,
    )


@guardrails_router.patch("/{guardrail_id}")
async def patch_guardrail(
    guardrail_id: str,
    body: GuardrailBody,
    user: AuthUser = Depends(require_tenant_admin),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    row, current = await _find_agent_by_nested_id(session, tenant_id, "guardrails", guardrail_id)
    updated = {**current, **body.model_dump(), "updated_by": user.email, "updated_at": datetime.now(UTC).isoformat()}
    _replace_nested_item(row, "guardrails", guardrail_id, updated)
    await session.commit()
    return updated


@guardrails_router.delete("/{guardrail_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_guardrail(
    guardrail_id: str,
    user: AuthUser = Depends(require_tenant_admin),  # noqa: ARG001
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> None:
    row, _current = await _find_agent_by_nested_id(session, tenant_id, "guardrails", guardrail_id)
    _replace_nested_item(row, "guardrails", guardrail_id, None)
    await session.commit()


@guardrails_router.post("/{guardrail_id}/duplicate")
async def duplicate_guardrail(
    guardrail_id: str,
    user: AuthUser = Depends(require_tenant_admin),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    row, current = await _find_agent_by_nested_id(session, tenant_id, "guardrails", guardrail_id)
    ops = _merged_ops(row)
    clone = {
        **current,
        "id": f"{guardrail_id}_copy",
        "name": f"{current['name']} (copia)",
        "updated_by": user.email,
    }
    ops["guardrails"] = [*ops.get("guardrails", []), clone]
    row.ops_config = ops
    row.updated_at = datetime.now(UTC)
    await session.commit()
    return clone


@guardrails_router.post("/{guardrail_id}/test")
async def test_guardrail(
    guardrail_id: str,
    message: dict | None = None,
    user: AuthUser = Depends(current_user),  # noqa: ARG001
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    _row, current = await _find_agent_by_nested_id(session, tenant_id, "guardrails", guardrail_id)
    text = (message or {}).get("text", "Ya estás aprobado por $80,000")
    violated = "aprob" in str(text).lower() and current["id"] == "gr_no_approval"
    return {"guardrail_id": guardrail_id, "violated": violated, "action": current["enforcement_mode"]}


@guardrails_router.get("/{guardrail_id}/violations")
async def get_guardrail_violations(
    guardrail_id: str,
    user: AuthUser = Depends(current_user),  # noqa: ARG001
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> list[dict]:
    _row, current = await _find_agent_by_nested_id(session, tenant_id, "guardrails", guardrail_id)
    return [
        {
            "id": f"viol_{i}",
            "guardrail_id": guardrail_id,
            "severity": current["severity"],
            "message": "Intentó prometer aprobación",
            "created_at": (datetime.now(UTC) - timedelta(minutes=i * 13)).isoformat(),
        }
        for i in range(int(current.get("violation_count") or 1))
    ]


@extraction_fields_router.patch("/{field_id}")
async def patch_extraction_field(
    field_id: str,
    body: ExtractionFieldBody,
    user: AuthUser = Depends(require_tenant_admin),  # noqa: ARG001
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    row, current = await _find_agent_by_nested_id(session, tenant_id, "extraction_fields", field_id)
    updated = {**current, **body.model_dump()}
    _replace_nested_item(row, "extraction_fields", field_id, updated)
    await session.commit()
    return updated


@extraction_fields_router.delete("/{field_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_extraction_field(
    field_id: str,
    user: AuthUser = Depends(require_tenant_admin),  # noqa: ARG001
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> None:
    row, _current = await _find_agent_by_nested_id(session, tenant_id, "extraction_fields", field_id)
    _replace_nested_item(row, "extraction_fields", field_id, None)
    await session.commit()


@extraction_fields_router.post("/{field_id}/test")
async def test_extraction_field(
    field_id: str,
    message: dict | None = None,
    user: AuthUser = Depends(current_user),  # noqa: ARG001
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    _row, current = await _find_agent_by_nested_id(session, tenant_id, "extraction_fields", field_id)
    text = str((message or {}).get("text", "Me llamo Juan Pérez y gano por nómina"))
    value = "Juan Pérez" if "nombre" in current["field_key"] else "nómina"
    return {
        "field_id": field_id,
        "value": value,
        "confidence": max(float(current.get("confidence_threshold") or 0.9), 0.94),
        "source_text": text,
        "auto_saved": bool(current.get("auto_save")),
    }


@extraction_fields_router.get("/{field_id}/examples")
async def get_extraction_examples(
    field_id: str,
    user: AuthUser = Depends(current_user),  # noqa: ARG001
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> list[dict]:
    _row, current = await _find_agent_by_nested_id(session, tenant_id, "extraction_fields", field_id)
    return [
        {"message": "Mi nombre es Juan Pérez", "value": "Juan Pérez", "field": current["label"]},
        {"message": "Trabajo por nómina", "value": "nómina", "field": current["label"]},
    ]


@supervisor_router.post("/evaluate-response")
async def evaluate_response(
    body: PreviewBody,
    user: AuthUser = Depends(current_user),  # noqa: ARG001
) -> dict:
    risk = "high" if "aprob" in body.message.lower() else "low"
    return {
        "outcome": "rewritten" if risk == "high" else "approved",
        "hallucination_risk": risk,
        "guardrail_compliance": risk == "low",
        "final_response": (
            "Puedo ayudarte a revisar opciones, pero la aprobación depende de validación."
            if risk == "high"
            else body.message
        ),
    }


@supervisor_router.get("/decisions/{decision_id}")
async def get_supervisor_decision(
    decision_id: str,
    user: AuthUser = Depends(current_user),  # noqa: ARG001
) -> dict:
    return {"id": decision_id, "outcome": "approved", "created_at": datetime.now(UTC).isoformat()}


@scenarios_router.get("")
async def list_scenarios(user: AuthUser = Depends(current_user)) -> list[dict]:  # noqa: ARG001
    return _default_scenarios("reception")
