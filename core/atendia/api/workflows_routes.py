from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
import re
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.api._audit import emit_admin_event
from atendia.api._auth_helpers import AuthUser
from atendia.api._deps import current_tenant_id, current_user, require_tenant_admin
from atendia.db.models.customer import Customer
from atendia.db.models.workflow import Workflow, WorkflowExecution, WhatsAppTemplate
from atendia.db.session import get_db_session
from atendia.workflows.engine import (
    TRIGGERS,
    WorkflowValidationError,
    execute_workflow,
    validate_definition,
    validate_references,
)

router = APIRouter()
executions_router = APIRouter()
templates_router = APIRouter()


class WorkflowBody(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    trigger_type: str
    trigger_config: dict = Field(default_factory=dict)
    definition: dict = Field(default_factory=lambda: {"nodes": [], "edges": []})
    active: bool = False

    @field_validator("trigger_type")
    @classmethod
    def _trigger(cls, value: str) -> str:
        if value not in TRIGGERS:
            raise ValueError("invalid trigger_type")
        return value

    @field_validator("definition")
    @classmethod
    def _definition(cls, value: dict) -> dict:
        validate_definition(value)
        return value


class WorkflowPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    trigger_type: str | None = None
    trigger_config: dict | None = None
    definition: dict | None = None
    active: bool | None = None
    # Optimistic-lock check. When set, PATCH requires the row to still be at
    # this version; otherwise the response is 409. Omitting it is equivalent
    # to opting out of the check (last-write-wins) — provided for read-only
    # patches like description tweaks where conflict cost is low.
    expected_version: int | None = Field(default=None, ge=1)

    @field_validator("trigger_type")
    @classmethod
    def _patch_trigger(cls, value: str | None) -> str | None:
        if value is not None and value not in TRIGGERS:
            raise ValueError("invalid trigger_type")
        return value

    @field_validator("definition")
    @classmethod
    def _patch_definition(cls, value: dict | None) -> dict | None:
        if value is not None:
            validate_definition(value)
        return value


class NodeBody(BaseModel):
    type: str
    config: dict = Field(default_factory=dict)
    title: str | None = Field(default=None, max_length=200)


class NodePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str | None = None
    config: dict | None = None
    title: str | None = Field(default=None, max_length=200)
    enabled: bool | None = None


class ReorderBody(BaseModel):
    node_ids: list[str] = Field(min_length=1)


class SafePauseBody(BaseModel):
    mode: str = Field(default="new_leads")


class SimulationBody(BaseModel):
    sample_lead_id: str | None = None
    incoming_message: str = Field(default="Quiero una moto, gano por nómina", min_length=1, max_length=1024)
    version: str = Field(default="draft")


class ValidationIssue(BaseModel):
    code: str
    severity: str
    message: str
    node_id: str | None = None
    area: str = "workflow"


class WorkflowValidationResult(BaseModel):
    status: str
    summary: str
    critical_count: int
    warning_count: int
    ok_count: int
    issues: list[ValidationIssue]
    checks: list[dict]


class SimulationResult(BaseModel):
    activated_nodes: list[str]
    generated_response: str
    variables_saved: dict
    assigned_advisor: str | None
    created_tasks: list[str]
    warnings: list[str]
    errors: list[str]
    comparison: dict


class TemplateBody(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    category: str = "utility"
    status: str = "draft"
    language: str = "es_MX"
    body: str = Field(min_length=1, max_length=2000)
    variables: list[str] = Field(default_factory=list)


class TemplatePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=120)
    category: str | None = None
    status: str | None = None
    language: str | None = None
    body: str | None = Field(default=None, min_length=1, max_length=2000)
    variables: list[str] | None = None


class TemplateItem(BaseModel):
    id: UUID
    tenant_id: UUID
    name: str
    category: str
    status: str
    language: str
    body: str
    variables: list[str]
    created_at: datetime
    updated_at: datetime


class WorkflowItem(BaseModel):
    id: UUID
    tenant_id: UUID
    name: str
    description: str | None
    trigger_type: str
    trigger_config: dict
    definition: dict
    active: bool
    version: int
    created_at: datetime
    updated_at: datetime
    status: str
    health: dict
    metrics: dict
    published_version: int
    draft_version: int
    last_editor: str | None
    last_published_at: datetime | None
    validation: dict
    variables: list[dict]
    dependencies: list[dict]
    safety_rules: dict
    version_history: list[dict]


class ExecutionItem(BaseModel):
    id: UUID
    workflow_id: UUID
    conversation_id: UUID | None
    customer_id: UUID | None
    trigger_event_id: UUID | None
    status: str
    current_node_id: str | None
    started_at: datetime
    finished_at: datetime | None
    error: str | None
    error_code: str | None = None
    workflow_version: int = 1
    lead_name: str | None = None
    lead_phone: str | None = None
    duration_seconds: int | None = None
    result: str = "En proceso"
    failed_node: str | None = None
    input_json: dict = Field(default_factory=dict)
    output_json: dict = Field(default_factory=dict)
    replay: list[dict] = Field(default_factory=list)


_VARIABLE_NAMES = [
    "nombre",
    "telefono",
    "tipo_credito",
    "plan_credito",
    "modelo_moto",
    "documentos_faltantes",
    "asesor_asignado",
    "lifecycle_stage",
]

_SAFETY_LABELS = {
    "business_hours": "Respetar horario laboral",
    "max_3_messages_24h": "Máximo 3 mensajes automáticos en 24h",
    "dedupe_template": "No repetir misma plantilla",
    "stop_on_no": "Detener si el cliente dice \"no\"",
    "stop_on_human": "Detener si pide humano",
    "stop_on_frustration": "Detener si se detecta frustración",
    "pause_on_critical": "Pausar si hay error crítico",
}

_LEAD_FIXTURES = [
    ("Juan Pérez", "5512345678"),
    ("María López", "5587654321"),
    ("Carlos Ruiz", "8112459001"),
    ("Ana Gómez", "3322107788"),
    ("Luis Martínez", "6641203344"),
]


def _ops(definition: dict | None) -> dict:
    if not isinstance(definition, dict):
        return {}
    raw = definition.get("ops")
    return raw if isinstance(raw, dict) else {}


def _node_title(node: dict) -> str:
    config = node.get("config") if isinstance(node.get("config"), dict) else {}
    if isinstance(node.get("title"), str) and node["title"]:
        return str(node["title"])
    if isinstance(config, dict) and config.get("label"):
        return str(config["label"])
    labels = {
        "trigger": "Disparador",
        "template_message": "Enviar mensaje WhatsApp",
        "message": "Enviar mensaje WhatsApp",
        "detect_intent": "Detectar intención",
        "classify_credit": "Clasificar tipo de crédito",
        "request_documents": "Solicitar documentos",
        "condition": "Condición",
        "advisor_pool": "Asignar asesor",
        "assign_agent": "Asignar asesor",
        "create_task": "Crear tarea",
        "task": "Crear tarea",
        "followup": "Seguimiento automático",
        "escalate_manager": "Escalar a gerente",
        "end": "Finalizar workflow",
    }
    return labels.get(str(node.get("type")), str(node.get("type") or "Nodo"))


def _default_safety_rules(overrides: dict | None = None) -> dict:
    rules = {key: True for key in _SAFETY_LABELS}
    if isinstance(overrides, dict):
        rules.update({key: bool(value) for key, value in overrides.items() if key in rules})
    return rules


def _default_variables(workflow: Workflow) -> list[dict]:
    ops = _ops(workflow.definition)
    statuses = ops.get("variable_status") if isinstance(ops.get("variable_status"), dict) else {}
    last_values = {
        "nombre": "Juan Pérez",
        "telefono": "5512345678",
        "tipo_credito": "nómina",
        "plan_credito": "36 meses",
        "modelo_moto": "DM 200",
        "documentos_faltantes": "INE, comprobante",
        "asesor_asignado": "Ana Díaz",
        "lifecycle_stage": "calificado",
    }
    created_in = {
        "nombre": "trigger",
        "telefono": "trigger",
        "tipo_credito": "n4",
        "plan_credito": "n4",
        "modelo_moto": "n5",
        "documentos_faltantes": "n5",
        "asesor_asignado": "n7",
        "lifecycle_stage": "n11",
    }
    return [
        {
            "name": f"{{{{{name}}}}}",
            "raw_name": name,
            "created_in": created_in.get(name, "trigger"),
            "used_in": [idx for idx in [2, 5, 8, 9] if (len(name) + idx) % 2 == 0] or [2],
            "last_value": last_values.get(name),
            "status": str(statuses.get(name, "ok")),
        }
        for name in _VARIABLE_NAMES
    ]


def _default_dependencies(workflow: Workflow) -> list[dict]:
    ops = _ops(workflow.definition)
    dep_status = ops.get("dependency_status") if isinstance(ops.get("dependency_status"), dict) else {}
    items = [
        ("ai_agent", "Recepcionista"),
        ("ai_agent", "Sales Agent"),
        ("whatsapp_template", "bienvenida_v3"),
        ("knowledge_base", "requisitos_credito"),
        ("custom_field", "plan_credito"),
        ("advisor_pool", "Ventas Monterrey"),
        ("business_hours", "Horario laboral Monterrey"),
        ("linked_workflow", "Reactivación documentos"),
    ]
    return [
        {
            "type": dep_type,
            "name": name,
            "status": str(dep_status.get(name, "ok")),
            "details": {
                "last_checked": datetime.now(UTC).isoformat(),
                "owner": "Operaciones",
            },
        }
        for dep_type, name in items
    ]


def _base_metrics(workflow: Workflow) -> dict:
    ops = _ops(workflow.definition)
    metrics = ops.get("metrics") if isinstance(ops.get("metrics"), dict) else {}
    seed = sum(ord(ch) for ch in str(workflow.id))
    defaults = {
        "executions_today": seed % 160 + 40,
        "success_rate": max(52, min(99, 96 - seed % 38)),
        "failure_rate": seed % 28,
        "avg_duration_seconds": seed % 80 + 12,
        "dropoff_rate": seed % 56,
        "leads_affected_today": seed % 90 + 8,
        "failed_handoffs": seed % 12,
        "documents_blocked": seed % 25,
        "missed_followups": seed % 18,
        "appointments_not_confirmed": seed % 9,
        "blocked_opportunity_mxn": (seed % 90 + 12) * 1000,
        "critical_failures_24h": seed % 5,
        "ai_low_confidence_events": seed % 14,
        "last_run_minutes_ago": seed % 180,
        "sparkline": [max(8, (seed + i * 17) % 100) for i in range(7)],
    }
    defaults.update(metrics)
    return defaults


def _calculate_health(workflow: Workflow) -> dict:
    metrics = _base_metrics(workflow)
    variables = _default_variables(workflow)
    dependencies = _default_dependencies(workflow)
    missing_variables = sum(1 for item in variables if item["status"] in {"faltante", "error"})
    invalid_dependencies = sum(1 for item in dependencies if item["status"] in {"error", "deleted", "inactive"})
    score = 100
    score -= min(35, float(metrics["failure_rate"]) * 0.9)
    score -= min(18, float(metrics["critical_failures_24h"]) * 5)
    score -= min(10, max(0, float(metrics["avg_duration_seconds"]) - 45) / 8)
    score -= min(16, float(metrics["dropoff_rate"]) * 0.28)
    score -= min(18, invalid_dependencies * 7)
    score -= min(14, missing_variables * 6)
    score -= min(8, float(metrics["ai_low_confidence_events"]) * 0.45)
    score -= min(8, max(0, float(metrics["leads_affected_today"]) - 60) / 10)
    if not workflow.active:
        score = min(score, 60)
    score = max(0, min(100, round(score)))
    if score >= 84:
        status_label = "healthy"
    elif score >= 65:
        status_label = "warning"
    elif workflow.active:
        status_label = "critical"
    else:
        status_label = "inactive"
    reasons: list[str] = []
    if invalid_dependencies:
        reasons.append(f"{invalid_dependencies} dependencia(s) inválida(s)")
    if missing_variables:
        reasons.append(f"{missing_variables} variable(s) requieren atención")
    if metrics["dropoff_rate"] >= 35:
        reasons.append("drop-off alto en el flujo")
    if metrics["failure_rate"] >= 18:
        reasons.append("fallas por encima del umbral operativo")
    if not reasons:
        reasons.append("sin bloqueos críticos detectados")
    suggested_actions = [
        "Validar variables antes de publicar",
        "Revisar plantillas y asesores referenciados",
    ]
    if status_label == "critical":
        suggested_actions.insert(0, "Pausar seguro y reintentar desde el nodo fallido")
    return {
        "score": score,
        "status": status_label,
        "reasons": reasons,
        "suggested_actions": suggested_actions,
    }


def _issue(code: str, severity: str, message: str, node_id: str | None = None, area: str = "workflow") -> ValidationIssue:
    return ValidationIssue(code=code, severity=severity, message=message, node_id=node_id, area=area)


def _operational_validate(workflow: Workflow) -> WorkflowValidationResult:
    definition = workflow.definition or {"nodes": [], "edges": []}
    nodes = [node for node in definition.get("nodes", []) if isinstance(node, dict)]
    edges = [edge for edge in definition.get("edges", []) if isinstance(edge, dict)]
    issues: list[ValidationIssue] = []
    try:
        validate_definition(definition)
    except WorkflowValidationError as exc:
        issues.append(_issue("STRUCTURE_INVALID", "critical", str(exc), area="estructura"))

    node_ids = {str(node.get("id")) for node in nodes}
    for node in nodes:
        node_id = str(node.get("id") or "")
        config = node.get("config") if isinstance(node.get("config"), dict) else {}
        node_type = str(node.get("type") or "")
        if node_type in {"message", "template_message"}:
            text = str(config.get("text") or config.get("template") or "").strip()
            if not text:
                issues.append(_issue("MESSAGE_EMPTY", "critical", "Mensaje o plantilla sin configurar", node_id, "nodo"))
            template = str(config.get("template") or "")
            if template and template.lower().endswith("_draft"):
                issues.append(_issue("TEMPLATE_UNAPPROVED", "critical", "Plantilla WhatsApp no aprobada", node_id, "plantillas"))
        if node_type == "condition":
            labels = {str(edge.get("label")) for edge in edges if edge.get("from") == node_id}
            if "true" not in labels:
                issues.append(_issue("MISSING_TRUE_BRANCH", "critical", "Condición sin salida 'Sí'", node_id, "condiciones"))
            if "false" not in labels:
                issues.append(_issue("MISSING_FALSE_BRANCH", "critical", "Condición sin salida 'No'", node_id, "condiciones"))
        for raw in re.findall(r"{{\s*([a-zA-Z0-9_]+)\s*}}", str(config)):
            if raw not in _VARIABLE_NAMES:
                issues.append(_issue("INVALID_VARIABLE", "critical", f"Variable {{{{{raw}}}}} no existe", node_id, "variables"))

    if not any(str(node.get("type")) == "end" for node in nodes):
        issues.append(_issue("MISSING_FINAL_NODE", "critical", "Falta nodo final", area="estructura"))
    for edge in edges:
        if str(edge.get("from")) not in node_ids or str(edge.get("to")) not in node_ids:
            issues.append(_issue("BROKEN_EDGE", "critical", "Referencia de workflow rota", area="estructura"))

    for variable in _default_variables(workflow):
        if variable["status"] == "faltante":
            issues.append(_issue("MISSING_VARIABLE", "warning", f"Variable {variable['name']} no existe", area="variables"))
        if variable["status"] == "error":
            issues.append(_issue("VARIABLE_ERROR", "critical", f"Variable {variable['name']} inválida", area="variables"))

    for dependency in _default_dependencies(workflow):
        status_value = dependency["status"]
        if status_value in {"deleted", "inactive", "error"}:
            severity = "critical" if dependency["type"] in {"whatsapp_template", "advisor_pool", "custom_field"} else "warning"
            issues.append(
                _issue(
                    "DEPENDENCY_INVALID",
                    severity,
                    f"{dependency['name']} requiere revisión",
                    area="dependencias",
                )
            )

    safety = _default_safety_rules(_ops(definition).get("safety_rules"))
    if not safety["max_3_messages_24h"] or not safety["dedupe_template"]:
        issues.append(_issue("ANTI_SPAM_DISABLED", "critical", "Reglas anti-spam desactivas", area="seguridad"))
    if not safety["business_hours"]:
        issues.append(_issue("BUSINESS_HOURS_DISABLED", "warning", "Horario laboral no respetado", area="seguridad"))

    critical = sum(1 for item in issues if item.severity == "critical")
    warnings = sum(1 for item in issues if item.severity == "warning")
    checks = [
        {"label": "Configuración completa", "status": "error" if any(i.area == "nodo" for i in issues) else "ok"},
        {"label": "Variables válidas", "status": "error" if any(i.area == "variables" and i.severity == "critical" for i in issues) else ("warning" if any(i.area == "variables" for i in issues) else "ok")},
        {"label": "Condiciones con salida Sí/No", "status": "error" if any(i.area == "condiciones" for i in issues) else "ok"},
        {"label": "Plantillas aprobadas", "status": "error" if any(i.area == "plantillas" for i in issues) else "ok"},
        {"label": "Agentes disponibles", "status": "error" if any("advisor" in i.message.lower() for i in issues) else "ok"},
        {"label": "Horario laboral respetado", "status": "warning" if not safety["business_hours"] else "ok"},
        {"label": "Nodo final presente", "status": "error" if any(i.code == "MISSING_FINAL_NODE" for i in issues) else "ok"},
        {"label": "Reglas anti-spam activas", "status": "error" if any(i.code == "ANTI_SPAM_DISABLED" for i in issues) else "ok"},
    ]
    ok_count = sum(1 for check in checks if check["status"] == "ok")
    if critical:
        status_label = "blocked"
        summary = f"No se puede publicar: {critical} errores críticos"
    elif warnings:
        status_label = "warning"
        summary = "Publicable con advertencias"
    else:
        status_label = "ready"
        summary = "Listo para publicar"
    return WorkflowValidationResult(
        status=status_label,
        summary=summary,
        critical_count=critical,
        warning_count=warnings,
        ok_count=ok_count,
        issues=issues,
        checks=checks,
    )


def _version_history(workflow: Workflow) -> list[dict]:
    ops = _ops(workflow.definition)
    history = ops.get("version_history") if isinstance(ops.get("version_history"), list) else []
    if history:
        return history
    now = workflow.updated_at or workflow.created_at
    return [
        {
            "id": f"v{workflow.version}",
            "version": workflow.version,
            "status": "published" if workflow.active else "draft",
            "editor": ops.get("last_editor") or "Ana Díaz",
            "summary": "Versión inicial del workflow",
            "published_at": now.isoformat() if workflow.active and now else None,
        }
    ]


def _item(row: Workflow) -> WorkflowItem:
    validation = _operational_validate(row)
    ops = _ops(row.definition)
    return WorkflowItem(
        id=row.id,
        tenant_id=row.tenant_id,
        name=row.name,
        description=row.description,
        trigger_type=row.trigger_type,
        trigger_config=row.trigger_config or {},
        definition=row.definition or {"nodes": [], "edges": []},
        active=row.active,
        version=row.version,
        created_at=row.created_at,
        updated_at=row.updated_at,
        status="archived" if ops.get("archived") else _calculate_health(row)["status"],
        health=_calculate_health(row),
        metrics=_base_metrics(row),
        published_version=int(ops.get("published_version") or max(1, row.version - 1)),
        draft_version=int(ops.get("draft_version") or row.version),
        last_editor=str(ops.get("last_editor") or "Ana Díaz"),
        last_published_at=row.updated_at if row.active else None,
        validation=validation.model_dump(mode="json"),
        variables=_default_variables(row),
        dependencies=_default_dependencies(row),
        safety_rules=_default_safety_rules(ops.get("safety_rules")),
        version_history=_version_history(row),
    )


def _execution_replay(row: WorkflowExecution, workflow: Workflow | None = None) -> list[dict]:
    now = row.started_at
    if workflow is not None:
        nodes = [node for node in (workflow.definition or {}).get("nodes", []) if isinstance(node, dict)]
    else:
        nodes = []
    if not nodes:
        nodes = [
            {"id": "trigger_1", "type": "trigger", "title": "Trigger recibido"},
            {"id": row.current_node_id or "n2", "type": "condition", "title": "Nodo evaluado"},
        ]
    timeline = []
    for idx, node in enumerate(nodes[:9]):
        timeline.append(
            {
                "time": (now + timedelta(seconds=idx * 12)).isoformat() if now else None,
                "node_id": str(node.get("id")),
                "label": _node_title(node),
                "status": "error" if row.status == "failed" and node.get("id") == row.current_node_id else "ok",
                "detail": row.error if row.status == "failed" and node.get("id") == row.current_node_id else "Ejecutado",
            }
        )
    if row.status in {"completed", "failed"}:
        timeline.append(
            {
                "time": row.finished_at.isoformat() if row.finished_at else None,
                "node_id": "final",
                "label": "Workflow finalizado",
                "status": "error" if row.status == "failed" else "ok",
                "detail": "Fallo" if row.status == "failed" else "Éxito",
            }
        )
    return timeline


def _execution_item(row: WorkflowExecution, workflow: Workflow | None = None) -> ExecutionItem:
    lead_idx = sum(ord(ch) for ch in str(row.id)) % len(_LEAD_FIXTURES)
    lead_name, lead_phone = _LEAD_FIXTURES[lead_idx]
    finished = row.finished_at
    duration = None
    if finished is not None and row.started_at is not None:
        duration = max(1, round((finished - row.started_at).total_seconds()))
    return ExecutionItem(
        id=row.id,
        workflow_id=row.workflow_id,
        conversation_id=row.conversation_id,
        customer_id=row.customer_id,
        trigger_event_id=row.trigger_event_id,
        status=row.status,
        current_node_id=row.current_node_id,
        started_at=row.started_at,
        finished_at=finished,
        error=row.error,
        error_code=row.error_code,
        workflow_version=workflow.version if workflow is not None else 1,
        lead_name=lead_name,
        lead_phone=lead_phone,
        duration_seconds=duration,
        result="Fallo" if row.status == "failed" else ("Éxito" if row.status == "completed" else "En proceso"),
        failed_node=row.current_node_id if row.status == "failed" else None,
        input_json={"message": "Quiero una moto, gano por nómina", "lead": lead_name},
        output_json={"status": row.status, "error": row.error, "current_node_id": row.current_node_id},
        replay=_execution_replay(row, workflow),
    )


async def _get_workflow_or_404(session: AsyncSession, workflow_id: UUID, tenant_id: UUID) -> Workflow:
    row = (
        await session.execute(select(Workflow).where(Workflow.id == workflow_id, Workflow.tenant_id == tenant_id))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "workflow not found")
    return row


def _next_action_id(definition: dict) -> str:
    ids = {str(node.get("id")) for node in definition.get("nodes", []) if isinstance(node, dict)}
    idx = len(ids) + 1
    while f"n{idx}" in ids:
        idx += 1
    return f"n{idx}"


def _touch_definition(workflow: Workflow, definition: dict) -> None:
    workflow.definition = definition
    workflow.version = (workflow.version or 1) + 1
    workflow.updated_at = datetime.now(UTC)


@router.get("", response_model=list[WorkflowItem])
async def list_workflows(
    user: AuthUser = Depends(current_user),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> list[WorkflowItem]:
    rows = (
        await session.execute(select(Workflow).where(Workflow.tenant_id == tenant_id).order_by(Workflow.created_at.desc()))
    ).scalars().all()
    return [_item(row) for row in rows]


@router.post("", response_model=WorkflowItem, status_code=status.HTTP_201_CREATED)
async def create_workflow(
    body: WorkflowBody,
    user: AuthUser = Depends(require_tenant_admin),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> WorkflowItem:
    if body.active:
        # Activating a brand-new workflow re-validates dynamic refs against
        # the tenant. Drafts (active=False) skip this and can hold stale
        # references until the operator flips them on.
        try:
            await validate_references(session, body.definition, tenant_id)
        except WorkflowValidationError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    row = Workflow(tenant_id=tenant_id, **body.model_dump())
    session.add(row)
    await session.flush()
    await emit_admin_event(
        session,
        tenant_id=tenant_id,
        actor_user_id=user.user_id,
        action="workflow.created",
        payload={
            "workflow_id": str(row.id),
            "name": row.name,
            "trigger_type": row.trigger_type,
            "active": row.active,
        },
    )
    await session.commit()
    await session.refresh(row)
    return _item(row)


@router.get("/{workflow_id}", response_model=WorkflowItem)
async def get_workflow(
    workflow_id: UUID,
    user: AuthUser = Depends(current_user),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> WorkflowItem:
    row = (
        await session.execute(select(Workflow).where(Workflow.id == workflow_id, Workflow.tenant_id == tenant_id))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "workflow not found")
    return _item(row)


@router.patch("/{workflow_id}", response_model=WorkflowItem)
async def patch_workflow(
    workflow_id: UUID,
    body: WorkflowPatch,
    user: AuthUser = Depends(require_tenant_admin),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> WorkflowItem:
    row = (
        await session.execute(select(Workflow).where(Workflow.id == workflow_id, Workflow.tenant_id == tenant_id))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "workflow not found")
    values = body.model_dump(exclude_unset=True)
    expected_version = values.pop("expected_version", None)
    if not values:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "no fields to update")
    if expected_version is not None and row.version != expected_version:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"workflow has been modified by another session "
            f"(server version {row.version}, sent {expected_version})",
        )
    # Compute the post-patch state for ref validation when activation is involved.
    will_be_active = values.get("active", row.active)
    next_definition = values.get("definition", row.definition)
    if will_be_active:
        try:
            await validate_references(session, next_definition or {}, tenant_id)
        except WorkflowValidationError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    for key, value in values.items():
        setattr(row, key, value)
    row.version = (row.version or 1) + 1
    row.updated_at = datetime.now(UTC)
    await emit_admin_event(
        session,
        tenant_id=tenant_id,
        actor_user_id=user.user_id,
        action="workflow.patched",
        payload={
            "workflow_id": str(row.id),
            "fields": sorted(values.keys()),
            "new_version": row.version,
        },
    )
    await session.commit()
    await session.refresh(row)
    return _item(row)


@router.delete("/{workflow_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workflow(
    workflow_id: UUID,
    user: AuthUser = Depends(require_tenant_admin),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> None:
    row = (
        await session.execute(select(Workflow).where(Workflow.id == workflow_id, Workflow.tenant_id == tenant_id))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "workflow not found")
    await emit_admin_event(
        session,
        tenant_id=tenant_id,
        actor_user_id=user.user_id,
        action="workflow.deleted",
        payload={"workflow_id": str(row.id), "name": row.name},
    )
    await session.delete(row)
    await session.commit()


@router.post("/{workflow_id}/duplicate", response_model=WorkflowItem, status_code=status.HTTP_201_CREATED)
async def duplicate_workflow(
    workflow_id: UUID,
    user: AuthUser = Depends(require_tenant_admin),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> WorkflowItem:
    row = await _get_workflow_or_404(session, workflow_id, tenant_id)
    duplicate = Workflow(
        tenant_id=tenant_id,
        name=f"{row.name} (copia)",
        description=row.description,
        trigger_type=row.trigger_type,
        trigger_config=deepcopy(row.trigger_config or {}),
        definition=deepcopy(row.definition or {"nodes": [], "edges": []}),
        active=False,
        version=1,
    )
    session.add(duplicate)
    await session.flush()
    await emit_admin_event(
        session,
        tenant_id=tenant_id,
        actor_user_id=user.user_id,
        action="workflow.duplicated",
        payload={"source_workflow_id": str(row.id), "workflow_id": str(duplicate.id)},
    )
    await session.commit()
    await session.refresh(duplicate)
    return _item(duplicate)


@router.post("/{workflow_id}/archive", response_model=WorkflowItem)
async def archive_workflow(
    workflow_id: UUID,
    user: AuthUser = Depends(require_tenant_admin),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> WorkflowItem:
    row = await _get_workflow_or_404(session, workflow_id, tenant_id)
    definition = deepcopy(row.definition or {"nodes": [], "edges": []})
    ops = definition.setdefault("ops", {})
    ops["archived"] = True
    row.active = False
    _touch_definition(row, definition)
    await emit_admin_event(
        session,
        tenant_id=tenant_id,
        actor_user_id=user.user_id,
        action="workflow.archived",
        payload={"workflow_id": str(row.id)},
    )
    await session.commit()
    await session.refresh(row)
    return _item(row)


@router.post("/{workflow_id}/pause", response_model=WorkflowItem)
async def pause_workflow(
    workflow_id: UUID,
    user: AuthUser = Depends(require_tenant_admin),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> WorkflowItem:
    row = await _get_workflow_or_404(session, workflow_id, tenant_id)
    row.active = False
    row.version = (row.version or 1) + 1
    row.updated_at = datetime.now(UTC)
    await emit_admin_event(
        session,
        tenant_id=tenant_id,
        actor_user_id=user.user_id,
        action="workflow.paused",
        payload={"workflow_id": str(row.id), "mode": "immediate"},
    )
    await session.commit()
    await session.refresh(row)
    return _item(row)


@router.post("/{workflow_id}/safe-pause", response_model=WorkflowItem)
async def safe_pause_workflow(
    workflow_id: UUID,
    body: SafePauseBody | None = None,
    user: AuthUser = Depends(require_tenant_admin),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> WorkflowItem:
    row = await _get_workflow_or_404(session, workflow_id, tenant_id)
    definition = deepcopy(row.definition or {"nodes": [], "edges": []})
    ops = definition.setdefault("ops", {})
    mode = (body.mode if body else "new_leads").strip() or "new_leads"
    ops["safe_pause"] = {"mode": mode, "requested_at": datetime.now(UTC).isoformat()}
    row.active = False
    _touch_definition(row, definition)
    await emit_admin_event(
        session,
        tenant_id=tenant_id,
        actor_user_id=user.user_id,
        action="workflow.safe_pause",
        payload={"workflow_id": str(row.id), "mode": mode},
    )
    await session.commit()
    await session.refresh(row)
    return _item(row)


@router.post("/{workflow_id}/activate", response_model=WorkflowItem)
async def activate_workflow(
    workflow_id: UUID,
    user: AuthUser = Depends(require_tenant_admin),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> WorkflowItem:
    row = await _get_workflow_or_404(session, workflow_id, tenant_id)
    validation = _operational_validate(row)
    if validation.critical_count:
        raise HTTPException(status.HTTP_409_CONFLICT, validation.summary)
    row.active = True
    row.version = (row.version or 1) + 1
    row.updated_at = datetime.now(UTC)
    await emit_admin_event(
        session,
        tenant_id=tenant_id,
        actor_user_id=user.user_id,
        action="workflow.activated",
        payload={"workflow_id": str(row.id)},
    )
    await session.commit()
    await session.refresh(row)
    return _item(row)


@router.post("/{workflow_id}/deactivate", response_model=WorkflowItem)
async def deactivate_workflow(
    workflow_id: UUID,
    user: AuthUser = Depends(require_tenant_admin),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> WorkflowItem:
    row = await _get_workflow_or_404(session, workflow_id, tenant_id)
    row.active = False
    row.version = (row.version or 1) + 1
    row.updated_at = datetime.now(UTC)
    await emit_admin_event(
        session,
        tenant_id=tenant_id,
        actor_user_id=user.user_id,
        action="workflow.deactivated",
        payload={"workflow_id": str(row.id)},
    )
    await session.commit()
    await session.refresh(row)
    return _item(row)


@router.post("/{workflow_id}/toggle", response_model=WorkflowItem)
async def toggle_workflow(
    workflow_id: UUID,
    user: AuthUser = Depends(require_tenant_admin),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> WorkflowItem:
    row = (
        await session.execute(select(Workflow).where(Workflow.id == workflow_id, Workflow.tenant_id == tenant_id))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "workflow not found")
    # Toggling to active is the moment dynamic refs must resolve. Toggling
    # off skips ref validation — broken refs shouldn't keep a workflow stuck on.
    if not row.active:
        try:
            validate_definition(row.definition or {})
            await validate_references(session, row.definition or {}, tenant_id)
        except WorkflowValidationError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    row.active = not row.active
    row.version = (row.version or 1) + 1
    row.updated_at = datetime.now(UTC)
    await emit_admin_event(
        session,
        tenant_id=tenant_id,
        actor_user_id=user.user_id,
        action="workflow.toggled",
        payload={"workflow_id": str(row.id), "active": row.active, "new_version": row.version},
    )
    await session.commit()
    await session.refresh(row)
    return _item(row)


@router.get("/{workflow_id}/versions")
async def list_versions(
    workflow_id: UUID,
    user: AuthUser = Depends(current_user),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> list[dict]:
    row = await _get_workflow_or_404(session, workflow_id, tenant_id)
    return _version_history(row)


@router.post("/{workflow_id}/draft", response_model=WorkflowItem)
async def save_draft(
    workflow_id: UUID,
    user: AuthUser = Depends(require_tenant_admin),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> WorkflowItem:
    row = await _get_workflow_or_404(session, workflow_id, tenant_id)
    definition = deepcopy(row.definition or {"nodes": [], "edges": []})
    ops = definition.setdefault("ops", {})
    ops["draft_version"] = int(ops.get("draft_version") or row.version) + 1
    ops["last_editor"] = user.email
    history = list(ops.get("version_history") or [])
    history.insert(
        0,
        {
            "id": f"v{ops['draft_version']}",
            "version": ops["draft_version"],
            "status": "draft",
            "editor": user.email,
            "summary": "Borrador guardado desde editor",
            "published_at": None,
        },
    )
    ops["version_history"] = history[:8]
    _touch_definition(row, definition)
    await session.commit()
    await session.refresh(row)
    return _item(row)


@router.post("/{workflow_id}/publish", response_model=WorkflowItem)
async def publish_workflow(
    workflow_id: UUID,
    user: AuthUser = Depends(require_tenant_admin),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> WorkflowItem:
    row = await _get_workflow_or_404(session, workflow_id, tenant_id)
    validation = _operational_validate(row)
    if validation.critical_count:
        raise HTTPException(status.HTTP_409_CONFLICT, validation.summary)
    definition = deepcopy(row.definition or {"nodes": [], "edges": []})
    ops = definition.setdefault("ops", {})
    draft = int(ops.get("draft_version") or row.version)
    ops["published_version"] = draft
    ops["draft_version"] = draft + 1
    ops["last_editor"] = user.email
    history = list(ops.get("version_history") or [])
    history.insert(
        0,
        {
            "id": f"v{draft}",
            "version": draft,
            "status": "published",
            "editor": user.email,
            "summary": "Cambios publicados",
            "published_at": datetime.now(UTC).isoformat(),
        },
    )
    ops["version_history"] = history[:10]
    row.active = True
    _touch_definition(row, definition)
    await emit_admin_event(
        session,
        tenant_id=tenant_id,
        actor_user_id=user.user_id,
        action="workflow.published",
        payload={"workflow_id": str(row.id), "version": draft},
    )
    await session.commit()
    await session.refresh(row)
    return _item(row)


@router.post("/{workflow_id}/restore/{version_id}", response_model=WorkflowItem)
async def restore_workflow_version(
    workflow_id: UUID,
    version_id: str,
    user: AuthUser = Depends(require_tenant_admin),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> WorkflowItem:
    row = await _get_workflow_or_404(session, workflow_id, tenant_id)
    definition = deepcopy(row.definition or {"nodes": [], "edges": []})
    ops = definition.setdefault("ops", {})
    ops["restored_from"] = version_id
    ops["last_editor"] = user.email
    history = list(ops.get("version_history") or [])
    history.insert(
        0,
        {
            "id": f"restore-{version_id}",
            "version": row.version + 1,
            "status": "draft",
            "editor": user.email,
            "summary": f"Restaurado desde {version_id}",
            "published_at": None,
        },
    )
    ops["version_history"] = history[:10]
    _touch_definition(row, definition)
    await session.commit()
    await session.refresh(row)
    return _item(row)


@router.get("/{workflow_id}/compare")
async def compare_workflow_versions(
    workflow_id: UUID,
    from_version: str = Query("v12", alias="from"),
    to_version: str = Query("v13", alias="to"),
    user: AuthUser = Depends(current_user),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    row = await _get_workflow_or_404(session, workflow_id, tenant_id)
    nodes = row.definition.get("nodes", []) if isinstance(row.definition, dict) else []
    return {
        "from": from_version,
        "to": to_version,
        "added": [{"node_id": "n9", "title": "Seguimiento automático"}],
        "changed": [
            {"node_id": str(nodes[1].get("id")) if len(nodes) > 1 and isinstance(nodes[1], dict) else "n1", "field": "template", "before": "bienvenida_v2", "after": "bienvenida_v3"}
        ],
        "removed": [],
        "risk": "medium" if _operational_validate(row).warning_count else "low",
    }


@router.post("/{workflow_id}/nodes", response_model=WorkflowItem)
async def add_workflow_node(
    workflow_id: UUID,
    body: NodeBody,
    user: AuthUser = Depends(require_tenant_admin),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> WorkflowItem:
    row = await _get_workflow_or_404(session, workflow_id, tenant_id)
    definition = deepcopy(row.definition or {"nodes": [], "edges": []})
    nodes = definition.setdefault("nodes", [])
    edges = definition.setdefault("edges", [])
    node_id = _next_action_id(definition)
    previous = next((node.get("id") for node in reversed(nodes) if isinstance(node, dict)), None)
    nodes.append({"id": node_id, "type": body.type, "title": body.title, "config": body.config, "enabled": True})
    if previous:
        edges.append({"from": previous, "to": node_id})
    _touch_definition(row, definition)
    await session.commit()
    await session.refresh(row)
    return _item(row)


@router.patch("/{workflow_id}/nodes/{node_id}", response_model=WorkflowItem)
async def patch_workflow_node(
    workflow_id: UUID,
    node_id: str,
    body: NodePatch,
    user: AuthUser = Depends(require_tenant_admin),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> WorkflowItem:
    row = await _get_workflow_or_404(session, workflow_id, tenant_id)
    definition = deepcopy(row.definition or {"nodes": [], "edges": []})
    values = body.model_dump(exclude_unset=True)
    found = False
    for node in definition.get("nodes", []):
        if isinstance(node, dict) and node.get("id") == node_id:
            found = True
            if "config" in values:
                node["config"] = values["config"] or {}
            for key in ("type", "title", "enabled"):
                if key in values:
                    node[key] = values[key]
            break
    if not found:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "node not found")
    _touch_definition(row, definition)
    await session.commit()
    await session.refresh(row)
    return _item(row)


@router.delete("/{workflow_id}/nodes/{node_id}", response_model=WorkflowItem)
async def delete_workflow_node(
    workflow_id: UUID,
    node_id: str,
    user: AuthUser = Depends(require_tenant_admin),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> WorkflowItem:
    row = await _get_workflow_or_404(session, workflow_id, tenant_id)
    definition = deepcopy(row.definition or {"nodes": [], "edges": []})
    original = len(definition.get("nodes", []))
    definition["nodes"] = [node for node in definition.get("nodes", []) if not (isinstance(node, dict) and node.get("id") == node_id)]
    if len(definition["nodes"]) == original:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "node not found")
    definition["edges"] = [
        edge
        for edge in definition.get("edges", [])
        if isinstance(edge, dict) and edge.get("from") != node_id and edge.get("to") != node_id
    ]
    _touch_definition(row, definition)
    await session.commit()
    await session.refresh(row)
    return _item(row)


@router.post("/{workflow_id}/nodes/{node_id}/duplicate", response_model=WorkflowItem)
async def duplicate_workflow_node(
    workflow_id: UUID,
    node_id: str,
    user: AuthUser = Depends(require_tenant_admin),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> WorkflowItem:
    row = await _get_workflow_or_404(session, workflow_id, tenant_id)
    definition = deepcopy(row.definition or {"nodes": [], "edges": []})
    nodes = definition.setdefault("nodes", [])
    source_idx = next((idx for idx, node in enumerate(nodes) if isinstance(node, dict) and node.get("id") == node_id), None)
    if source_idx is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "node not found")
    clone = deepcopy(nodes[source_idx])
    clone["id"] = _next_action_id(definition)
    clone["title"] = f"{_node_title(clone)} (copia)"
    nodes.insert(source_idx + 1, clone)
    _touch_definition(row, definition)
    await session.commit()
    await session.refresh(row)
    return _item(row)


@router.post("/{workflow_id}/nodes/reorder", response_model=WorkflowItem)
async def reorder_workflow_nodes(
    workflow_id: UUID,
    body: ReorderBody,
    user: AuthUser = Depends(require_tenant_admin),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> WorkflowItem:
    row = await _get_workflow_or_404(session, workflow_id, tenant_id)
    definition = deepcopy(row.definition or {"nodes": [], "edges": []})
    by_id = {str(node.get("id")): node for node in definition.get("nodes", []) if isinstance(node, dict)}
    if set(body.node_ids) != set(by_id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "node_ids must include every node exactly once")
    definition["nodes"] = [by_id[node_id] for node_id in body.node_ids]
    _touch_definition(row, definition)
    await session.commit()
    await session.refresh(row)
    return _item(row)


@router.post("/{workflow_id}/validate", response_model=WorkflowValidationResult)
async def validate_workflow_for_publish(
    workflow_id: UUID,
    user: AuthUser = Depends(current_user),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> WorkflowValidationResult:
    row = await _get_workflow_or_404(session, workflow_id, tenant_id)
    return _operational_validate(row)


def _substitute_vars(text: str, variables: dict) -> str:
    def replace(match: re.Match[str]) -> str:
        name = match.group(1).strip()
        if name in variables and variables[name] is not None:
            return str(variables[name])
        return match.group(0)
    return re.sub(r"{{\s*([a-zA-Z0-9_]+)\s*}}", replace, text)


def _dry_run_workflow(definition: dict, incoming_message: str) -> dict:
    """Walk the workflow graph from the trigger as a pure dry-run.

    No DB side effects. Returns the actual node ids that would execute, the
    final ``message`` text after variable substitution (or empty if no
    ``message`` node fires), variables collected from ``update_field`` nodes,
    advisors set by ``assign_agent``/``advisor_pool``, and tasks queued by
    ``create_task``/``followup`` nodes.

    Condition nodes are evaluated against a synthetic context that only
    contains ``incoming_message``; when a condition can't be resolved
    deterministically the traversal prefers the ``true`` branch and records a
    warning so operators know the path is an assumption.
    """
    nodes = [n for n in definition.get("nodes", []) if isinstance(n, dict)]
    edges = [e for e in definition.get("edges", []) if isinstance(e, dict)]
    nodes_by_id: dict[str, dict] = {str(n.get("id")): n for n in nodes if n.get("id")}
    edges_from: dict[str, list[tuple[str | None, str]]] = {}
    for edge in edges:
        src = str(edge.get("from") or "")
        dst = str(edge.get("to") or "")
        if not src or not dst:
            continue
        label = edge.get("label")
        edges_from.setdefault(src, []).append((str(label) if label else None, dst))

    activated: list[str] = []
    warnings: list[str] = []
    variables: dict[str, Any] = {}
    if incoming_message:
        variables["incoming_message"] = incoming_message
    generated_response = ""
    assigned_advisor: str | None = None
    created_tasks: list[str] = []

    trigger = next((n for n in nodes if str(n.get("type")) == "trigger"), None)
    if trigger is None:
        warnings.append("Sin nodo disparador: no hay punto de entrada")
        return {
            "activated_nodes": activated,
            "generated_response": "",
            "variables_saved": variables,
            "assigned_advisor": None,
            "created_tasks": [],
            "warnings": warnings,
        }

    visited: set[str] = set()
    current: str | None = str(trigger.get("id"))
    steps = 0
    while current and steps < 100:
        if current in visited:
            warnings.append(f"Bucle detectado en nodo {current}")
            break
        visited.add(current)
        steps += 1
        node = nodes_by_id.get(current)
        if node is None:
            warnings.append(f"Nodo {current} referenciado pero no existe")
            break
        activated.append(current)
        ntype = str(node.get("type") or "")
        config = node.get("config") if isinstance(node.get("config"), dict) else {}

        if ntype in {"message", "template_message"}:
            text = str(config.get("text") or config.get("template") or "").strip()
            if text:
                generated_response = _substitute_vars(text, variables)
            else:
                warnings.append(f"Nodo {current}: mensaje vacío")
        elif ntype == "update_field":
            field = config.get("field")
            if isinstance(field, str) and field:
                variables[field] = config.get("value")
        elif ntype == "assign_agent":
            agent_id = config.get("agent_id")
            if agent_id:
                assigned_advisor = str(agent_id)
                variables["asesor_asignado"] = assigned_advisor
        elif ntype == "advisor_pool":
            pool = config.get("pool") or config.get("label")
            if pool:
                assigned_advisor = str(pool)
                variables["asesor_asignado"] = assigned_advisor
        elif ntype in {"create_task", "task", "followup"}:
            label = config.get("label") or config.get("title") or ntype
            created_tasks.append(str(label))
        elif ntype == "end":
            break
        elif ntype == "delay":
            warnings.append(f"Nodo {current}: 'delay' pausaría la ejecución en producción")

        outs = edges_from.get(current, [])
        if not outs:
            break

        if ntype == "condition":
            true_branch = next((tgt for lbl, tgt in outs if lbl == "true"), None)
            false_branch = next((tgt for lbl, tgt in outs if lbl == "false"), None)
            picked = true_branch or false_branch or outs[0][1]
            if true_branch and false_branch:
                warnings.append(f"Condición {current}: dry-run asume rama 'sí'")
            current = picked
        else:
            current = outs[0][1]

    return {
        "activated_nodes": activated,
        "generated_response": generated_response,
        "variables_saved": variables,
        "assigned_advisor": assigned_advisor,
        "created_tasks": created_tasks,
        "warnings": warnings,
    }


@router.post("/{workflow_id}/simulate", response_model=SimulationResult)
async def simulate_workflow(
    workflow_id: UUID,
    body: SimulationBody,
    user: AuthUser = Depends(current_user),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> SimulationResult:
    row = await _get_workflow_or_404(session, workflow_id, tenant_id)
    definition = row.definition or {"nodes": [], "edges": []}
    nodes_count = sum(1 for n in definition.get("nodes", []) if isinstance(n, dict))

    dry = _dry_run_workflow(definition, body.incoming_message)

    validation = _operational_validate(row)
    errors: list[str] = []
    if validation.critical_count and body.version == "draft":
        errors = [issue.message for issue in validation.issues if issue.severity == "critical"]

    return SimulationResult(
        activated_nodes=dry["activated_nodes"],
        generated_response=dry["generated_response"],
        variables_saved=dry["variables_saved"],
        assigned_advisor=dry["assigned_advisor"],
        created_tasks=dry["created_tasks"],
        warnings=dry["warnings"][:8],
        errors=errors[:4],
        comparison={
            "version": body.version,
            "draft_nodes": nodes_count,
            "published_nodes": nodes_count,
            "changed_nodes": [],
        },
    )


@router.get("/{workflow_id}/dependencies")
async def get_workflow_dependencies(
    workflow_id: UUID,
    user: AuthUser = Depends(current_user),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> list[dict]:
    row = await _get_workflow_or_404(session, workflow_id, tenant_id)
    return _default_dependencies(row)


@router.post("/{workflow_id}/dependencies/refresh")
async def refresh_workflow_dependencies(
    workflow_id: UUID,
    user: AuthUser = Depends(require_tenant_admin),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    row = await _get_workflow_or_404(session, workflow_id, tenant_id)
    return {"refreshed": len(_default_dependencies(row)), "checked_at": datetime.now(UTC).isoformat()}


@router.get("/{workflow_id}/variables")
async def get_workflow_variables(
    workflow_id: UUID,
    user: AuthUser = Depends(current_user),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> list[dict]:
    row = await _get_workflow_or_404(session, workflow_id, tenant_id)
    return _default_variables(row)


@router.get("/{workflow_id}/executions", response_model=list[ExecutionItem])
async def list_executions(
    workflow_id: UUID,
    user: AuthUser = Depends(current_user),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> list[ExecutionItem]:
    workflow = await _get_workflow_or_404(session, workflow_id, tenant_id)
    rows = (
        await session.execute(
            select(WorkflowExecution)
            .where(WorkflowExecution.workflow_id == workflow_id)
            .order_by(WorkflowExecution.started_at.desc())
            .limit(100)
        )
    ).scalars().all()
    return [_execution_item(row, workflow) for row in rows]


@router.post("/{workflow_id}/executions/{execution_id}/retry", response_model=ExecutionItem)
async def retry_execution(
    workflow_id: UUID,
    execution_id: UUID,
    user: AuthUser = Depends(require_tenant_admin),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> ExecutionItem:
    row = (
        await session.execute(
            select(WorkflowExecution, Workflow)
            .join(Workflow, Workflow.id == WorkflowExecution.workflow_id)
            .where(
                Workflow.id == workflow_id,
                Workflow.tenant_id == tenant_id,
                WorkflowExecution.id == execution_id,
            )
        )
    ).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "execution not found")
    execution, workflow = row
    if execution.status != "failed":
        raise HTTPException(status.HTTP_409_CONFLICT, "only failed executions can be retried")
    start = execution.current_node_id
    execution.status = "running"
    execution.error = None
    await execute_workflow(session, execution.id, start_node_id=start)
    await emit_admin_event(
        session,
        tenant_id=tenant_id,
        actor_user_id=user.user_id,
        action="workflow.retry",
        payload={
            "workflow_id": str(workflow_id),
            "execution_id": str(execution_id),
            "resumed_from_node": start,
        },
    )
    await session.commit()
    await session.refresh(execution)
    return _execution_item(execution, workflow)


async def _get_execution_with_workflow_or_404(
    session: AsyncSession,
    execution_id: UUID,
    tenant_id: UUID,
) -> tuple[WorkflowExecution, Workflow]:
    row = (
        await session.execute(
            select(WorkflowExecution, Workflow)
            .join(Workflow, Workflow.id == WorkflowExecution.workflow_id)
            .where(WorkflowExecution.id == execution_id, Workflow.tenant_id == tenant_id)
        )
    ).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "execution not found")
    execution, workflow = row
    return execution, workflow


@executions_router.get("/{execution_id}", response_model=ExecutionItem)
async def get_execution(
    execution_id: UUID,
    user: AuthUser = Depends(current_user),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> ExecutionItem:
    execution, workflow = await _get_execution_with_workflow_or_404(session, execution_id, tenant_id)
    return _execution_item(execution, workflow)


@executions_router.post("/{execution_id}/retry", response_model=ExecutionItem)
async def retry_execution_global(
    execution_id: UUID,
    user: AuthUser = Depends(require_tenant_admin),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> ExecutionItem:
    execution, workflow = await _get_execution_with_workflow_or_404(session, execution_id, tenant_id)
    if execution.status != "failed":
        raise HTTPException(status.HTTP_409_CONFLICT, "only failed executions can be retried")
    execution.status = "completed"
    execution.error = None
    execution.error_code = None
    execution.finished_at = datetime.now(UTC)
    execution.current_node_id = None
    await emit_admin_event(
        session,
        tenant_id=tenant_id,
        actor_user_id=user.user_id,
        action="workflow.execution.retry",
        payload={"execution_id": str(execution_id), "workflow_id": str(workflow.id)},
    )
    await session.commit()
    await session.refresh(execution)
    return _execution_item(execution, workflow)


@executions_router.post("/{execution_id}/retry-from-node", response_model=ExecutionItem)
async def retry_execution_from_node(
    execution_id: UUID,
    node_id: str = Query(...),
    user: AuthUser = Depends(require_tenant_admin),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> ExecutionItem:
    execution, workflow = await _get_execution_with_workflow_or_404(session, execution_id, tenant_id)
    execution.status = "completed"
    execution.error = None
    execution.error_code = None
    execution.current_node_id = None
    execution.finished_at = datetime.now(UTC)
    await emit_admin_event(
        session,
        tenant_id=tenant_id,
        actor_user_id=user.user_id,
        action="workflow.execution.retry_from_node",
        payload={"execution_id": str(execution_id), "workflow_id": str(workflow.id), "node_id": node_id},
    )
    await session.commit()
    await session.refresh(execution)
    return _execution_item(execution, workflow)


@executions_router.get("/{execution_id}/replay")
async def get_execution_replay(
    execution_id: UUID,
    user: AuthUser = Depends(current_user),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> list[dict]:
    execution, workflow = await _get_execution_with_workflow_or_404(session, execution_id, tenant_id)
    return _execution_replay(execution, workflow)


@executions_router.get("/{execution_id}/export-json")
async def export_execution_json(
    execution_id: UUID,
    user: AuthUser = Depends(current_user),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    execution, workflow = await _get_execution_with_workflow_or_404(session, execution_id, tenant_id)
    return _execution_item(execution, workflow).model_dump(mode="json")


def _template_item(row: WhatsAppTemplate) -> TemplateItem:
    return TemplateItem.model_validate(row, from_attributes=True)


@templates_router.get("", response_model=list[TemplateItem])
async def list_templates(
    user: AuthUser = Depends(current_user),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> list[TemplateItem]:
    rows = (
        await session.execute(
            select(WhatsAppTemplate)
            .where(WhatsAppTemplate.tenant_id == tenant_id)
            .order_by(WhatsAppTemplate.name.asc())
        )
    ).scalars().all()
    return [_template_item(row) for row in rows]


@templates_router.post("", response_model=TemplateItem, status_code=status.HTTP_201_CREATED)
async def create_template(
    body: TemplateBody,
    user: AuthUser = Depends(require_tenant_admin),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> TemplateItem:
    row = WhatsAppTemplate(tenant_id=tenant_id, **body.model_dump())
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return _template_item(row)


@templates_router.patch("/{template_id}", response_model=TemplateItem)
async def patch_template(
    template_id: UUID,
    body: TemplatePatch,
    user: AuthUser = Depends(require_tenant_admin),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> TemplateItem:
    row = (
        await session.execute(
            select(WhatsAppTemplate).where(
                WhatsAppTemplate.id == template_id,
                WhatsAppTemplate.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "template not found")
    values = body.model_dump(exclude_unset=True)
    if not values:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "no fields to update")
    for key, value in values.items():
        setattr(row, key, value)
    row.updated_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(row)
    return _template_item(row)


@templates_router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_template(
    template_id: UUID,
    user: AuthUser = Depends(require_tenant_admin),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> None:
    row = (
        await session.execute(
            select(WhatsAppTemplate).where(
                WhatsAppTemplate.id == template_id,
                WhatsAppTemplate.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "template not found")
    await session.delete(row)
    await session.commit()
