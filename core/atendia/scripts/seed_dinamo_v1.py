"""Seed Dinamo's Product-First tenant runtime configuration.

Phase A of ``DINAMO_TENANT_RUNTIME_PLAN_V1.md`` only prepares tenant-scoped
configuration. It does not enable WhatsApp, outbox writes, live send, Google
side effects, smoke, canary, or production traffic.

Usage:
    PYTHONPATH=. uv run python -m atendia.scripts.seed_dinamo_v1 \
        --tenant-id <uuid> \
        [--requirements-path docs/tenant_sources/dinamo/Requisitos_Credito_Dinamo.json] \
        [--dry-run]
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import json
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.contact_memory.policy import merge_policy_options
from atendia.db.models.agent import Agent
from atendia.db.models.customer_fields import CustomerFieldDefinition
from atendia.db.models.product_agent import (
    AgentDeployment,
    AgentFieldPermission,
    AgentToolBinding,
    AgentVersion,
    AgentWorkflowBinding,
)
from atendia.db.models.tenant_config import TenantPipeline
from atendia.db.models.workflow import WhatsAppTemplate, Workflow

SEED_ID = "dinamo_tenant_runtime_plan_v1"
SOURCE_VERSION_ID = "DINAMO_TENANT_RUNTIME_PLAN_V1:2026-06-11"
AGENT_NAME = "Francisco Esparza - Dinamo"
AGENT_ROLE = "credit_advisor"
TENANT_TIMEZONE = "America/Mexico_City"
PLAN_APPROVAL_STATUS = "PLAN_APPROVED_READY_TO_IMPLEMENT"
DEFAULT_REQUIREMENTS_PATH = (
    Path(__file__).resolve().parents[3]
    / "docs"
    / "tenant_sources"
    / "dinamo"
    / "Requisitos_Credito_Dinamo.json"
)


@dataclass(frozen=True)
class FieldSpec:
    key: str
    label: str
    field_type: str
    ordering: int
    choices: tuple[str, ...] = ()
    visibility: str = "operator"
    aliases: tuple[str, ...] = ()
    write_owner: str = "ai"
    ai_can_write: bool = True
    evidence_required: bool = True
    extractable_by_ai: bool = True
    write_policy: str = "ai_auto"
    description: str | None = None
    derived_from: str | None = None


@dataclass(frozen=True)
class TemplateSpec:
    name: str
    body: str
    variables: tuple[str, ...] = ()


@dataclass(frozen=True)
class WorkflowSpec:
    key: str
    name: str
    trigger_type: str
    event_type: str
    nodes: tuple[dict[str, Any], ...]
    edges: tuple[dict[str, Any], ...] = ()
    customer_message_request_only: bool = False


@dataclass
class SeedResult:
    tenant_id: str
    dry_run: bool
    created_fields: list[str] = field(default_factory=list)
    updated_fields: list[str] = field(default_factory=list)
    archived_fields: list[str] = field(default_factory=list)
    created_templates: list[str] = field(default_factory=list)
    updated_templates: list[str] = field(default_factory=list)
    created_workflows: list[str] = field(default_factory=list)
    updated_workflows: list[str] = field(default_factory=list)
    created_permissions: list[str] = field(default_factory=list)
    updated_permissions: list[str] = field(default_factory=list)
    created_tool_bindings: list[str] = field(default_factory=list)
    updated_tool_bindings: list[str] = field(default_factory=list)
    created_workflow_bindings: list[str] = field(default_factory=list)
    updated_workflow_bindings: list[str] = field(default_factory=list)
    pipeline_action: str = "unchanged"
    agent_action: str = "unchanged"
    version_action: str = "unchanged"
    deployment_action: str = "unchanged"

    def as_dict(self) -> dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "dry_run": self.dry_run,
            "created_fields": self.created_fields,
            "updated_fields": self.updated_fields,
            "archived_fields": self.archived_fields,
            "created_templates": self.created_templates,
            "updated_templates": self.updated_templates,
            "created_workflows": self.created_workflows,
            "updated_workflows": self.updated_workflows,
            "created_permissions": self.created_permissions,
            "updated_permissions": self.updated_permissions,
            "created_tool_bindings": self.created_tool_bindings,
            "updated_tool_bindings": self.updated_tool_bindings,
            "created_workflow_bindings": self.created_workflow_bindings,
            "updated_workflow_bindings": self.updated_workflow_bindings,
            "pipeline_action": self.pipeline_action,
            "agent_action": self.agent_action,
            "version_action": self.version_action,
            "deployment_action": self.deployment_action,
        }


PLAN_CREDITO_CHOICES = (
    "Nómina Tarjeta",
    "Nómina Recibos",
    "Pensionados",
    "Negocio SAT",
    "Sin Comprobantes",
    "Guardia de Seguridad",
)
PLAN_ENGANCHE_CHOICES = ("10%", "15%", "20%", "30%")
PLAN_ENGANCHE_BY_PLAN = {
    "Nómina Tarjeta": "10%",
    "Nómina Recibos": "15%",
    "Pensionados": "10%",
    "Negocio SAT": "15%",
    "Sin Comprobantes": "20%",
    "Guardia de Seguridad": "30%",
}
PERIODICIDAD_CHOICES = ("semanal", "quincenal", "catorcenal", "mensual", "desconocido")
FORMULARIO_CHOICES = ("pendiente", "enviado", "completado_manual", "completado_webhook")
HANDOFF_REASON_CHOICES = (
    "pago_reportado",
    "humano_solicitado",
    "expediente_completo",
    "documento_dudoso",
    "enojo_fuerte",
    "excepcion_no_cubierta",
    "conflicto_promesa_externa",
    "fuera_de_nl",
    "otro",
)
NL_CHOICES = ("si", "no", "desconocido")

FIELD_SPECS: tuple[FieldSpec, ...] = (
    FieldSpec(
        "Cumple_Antiguedad",
        "Cumple Antiguedad",
        "checkbox",
        10,
        aliases=("antiguedad_ok", "cumple_antiguedad", "seniority_eligible"),
    ),
    FieldSpec(
        "Antiguedad_Laboral",
        "Antiguedad Laboral",
        "text",
        20,
        aliases=("antiguedad", "tiempo_trabajando", "seniority_raw"),
    ),
    FieldSpec(
        "Plan_Credito",
        "Plan Credito",
        "select",
        30,
        choices=PLAN_CREDITO_CHOICES,
        aliases=("plan_credito", "tipo_credito", "credito_plan", "PLAN"),
    ),
    FieldSpec(
        "Plan_Enganche",
        "Plan Enganche",
        "select",
        40,
        choices=PLAN_ENGANCHE_CHOICES,
        aliases=("enganche", "enganche_porcentaje", "tipo_enganche"),
        write_owner="system_derived",
        ai_can_write=False,
        extractable_by_ai=False,
        write_policy="human_only",
        derived_from="Plan_Credito",
    ),
    FieldSpec(
        "Moto",
        "Moto",
        "text",
        50,
        aliases=("modelo_moto", "modelo_interes", "MODELO_INTERES", "producto"),
        description="Canonical catalog model confirmed by catalog.search or quote.resolve.",
    ),
    FieldSpec("Banco", "Banco", "text", 60),
    FieldSpec(
        "Periodicidad_Pago",
        "Periodicidad Pago",
        "select",
        70,
        choices=PERIODICIDAD_CHOICES,
        aliases=("frecuencia_pago", "periodicidad"),
    ),
    FieldSpec("Fecha_Corte_Estado", "Fecha Corte Estado", "text", 80),
    FieldSpec(
        "Docs_Checklist",
        "Docs Checklist",
        "text",
        90,
        write_owner="system",
        ai_can_write=False,
        extractable_by_ai=False,
        write_policy="human_only",
    ),
    FieldSpec(
        "Doc_Incompletos",
        "Doc Incompletos",
        "text",
        100,
        write_owner="system",
        ai_can_write=False,
        extractable_by_ai=False,
        write_policy="human_only",
    ),
    FieldSpec(
        "Doc_Completos",
        "Doc Completos",
        "checkbox",
        110,
        write_owner="system",
        ai_can_write=False,
        extractable_by_ai=False,
        write_policy="human_only",
    ),
    FieldSpec(
        "Cotizacion_Enviada",
        "Cotizacion Enviada",
        "checkbox",
        120,
        write_owner="system",
        ai_can_write=False,
        extractable_by_ai=False,
        write_policy="human_only",
    ),
    FieldSpec(
        "Ultima_Cotizacion",
        "Ultima Cotizacion",
        "text",
        130,
        aliases=("ultima_cotizacion", "last_quote"),
        write_owner="system",
        ai_can_write=False,
        extractable_by_ai=False,
        write_policy="human_only",
    ),
    FieldSpec(
        "Formulario",
        "Formulario",
        "select",
        140,
        choices=FORMULARIO_CHOICES,
        write_owner="system_human",
        ai_can_write=False,
        extractable_by_ai=False,
        write_policy="human_only",
    ),
    FieldSpec(
        "Asesor_Asignado",
        "Asesor Asignado",
        "text",
        150,
        write_owner="system_human",
        ai_can_write=False,
        extractable_by_ai=False,
        write_policy="human_only",
    ),
    FieldSpec(
        "Handoff_Humano",
        "Handoff Humano",
        "checkbox",
        160,
        aliases=("needs_human", "handoff", "human_handoff"),
        write_owner="workflow",
    ),
    FieldSpec(
        "Motivo_Handoff",
        "Motivo Handoff",
        "select",
        170,
        choices=HANDOFF_REASON_CHOICES,
        write_owner="system",
        ai_can_write=False,
        extractable_by_ai=False,
        write_policy="human_only",
    ),
    FieldSpec(
        "Pago_Enganche_Reportado",
        "Pago Enganche Reportado",
        "checkbox",
        180,
        write_owner="system",
        ai_can_write=False,
        extractable_by_ai=False,
        write_policy="human_only",
    ),
    FieldSpec(
        "Vive_o_Trabaja_NL",
        "Vive o Trabaja NL",
        "select",
        190,
        choices=NL_CHOICES,
        aliases=("vive_trabaja_nl", "ubicacion_nl"),
    ),
    FieldSpec(
        "Transcripcion_Ultimo_Audio",
        "Transcripcion Ultimo Audio",
        "text",
        200,
        write_owner="system",
        ai_can_write=False,
        extractable_by_ai=False,
        write_policy="human_only",
    ),
    FieldSpec(
        "Autorizado",
        "Autorizado",
        "checkbox",
        210,
        write_owner="human_admin",
        ai_can_write=False,
        extractable_by_ai=False,
        write_policy="human_only",
    ),
    FieldSpec(
        "Solicitud_ID",
        "Solicitud ID",
        "text",
        220,
        visibility="admin",
        write_owner="system",
        ai_can_write=False,
        extractable_by_ai=False,
        write_policy="human_only",
    ),
    FieldSpec(
        "Google_Sheets_Row_ID",
        "Google Sheets Row ID",
        "text",
        230,
        visibility="admin",
        write_owner="system",
        ai_can_write=False,
        extractable_by_ai=False,
        write_policy="human_only",
    ),
    FieldSpec(
        "Google_Drive_Folder_ID",
        "Google Drive Folder ID",
        "text",
        240,
        visibility="admin",
        write_owner="system",
        ai_can_write=False,
        extractable_by_ai=False,
        write_policy="human_only",
    ),
    FieldSpec(
        "Google_Drive_File_IDs",
        "Google Drive File IDs",
        "text",
        250,
        visibility="admin",
        write_owner="system",
        ai_can_write=False,
        extractable_by_ai=False,
        write_policy="human_only",
    ),
    FieldSpec(
        "Source_Version_ID",
        "Source Version ID",
        "text",
        260,
        visibility="admin",
        write_owner="system",
        ai_can_write=False,
        extractable_by_ai=False,
        write_policy="human_only",
    ),
    FieldSpec(
        "Last_Runtime_Trace_ID",
        "Last Runtime Trace ID",
        "text",
        270,
        visibility="admin",
        write_owner="system",
        ai_can_write=False,
        extractable_by_ai=False,
        write_policy="human_only",
    ),
    FieldSpec(
        "Followups_Enviados",
        "Followups Enviados",
        "number",
        280,
        visibility="admin",
        write_owner="system",
        ai_can_write=False,
        extractable_by_ai=False,
        write_policy="human_only",
    ),
    FieldSpec(
        "Proximo_Followup",
        "Proximo Followup",
        "date",
        290,
        visibility="admin",
        write_owner="system",
        ai_can_write=False,
        extractable_by_ai=False,
        write_policy="human_only",
    ),
)

TEMPLATE_SPECS: tuple[TemplateSpec, ...] = (
    TemplateSpec(
        "dinamo_handoff_general_v1",
        "Déjame revisarlo bien y te confirmo por aquí en un momento.",
    ),
    TemplateSpec(
        "dinamo_payment_reported_v1",
        (
            "Si ya diste enganche o hiciste un pago, eso lo reviso directo antes de "
            "mover cualquier dato. Dame un momento y te confirmo por aquí."
        ),
    ),
    TemplateSpec(
        "dinamo_hostile_after_handoff_v1",
        "Va, lo dejamos aquí por ahora. En cuanto tenga la revisión te escribo por aquí.",
    ),
    TemplateSpec(
        "dinamo_document_invalid_v1",
        (
            "Me llegó, pero así no alcanza para validarlo: {motivo}. Mándamelo "
            "completo, claro y legible para poder avanzar."
        ),
        ("motivo",),
    ),
    TemplateSpec(
        "dinamo_document_accepted_next_missing_v1",
        (
            "Perfecto, {documento_recibido} ya quedó recibido. Ahorita solo "
            "falta {documento_faltante}."
        ),
        ("documento_recibido", "documento_faltante"),
    ),
    TemplateSpec(
        "dinamo_expediente_complete_v1",
        (
            "Perfecto, ya con eso queda tu expediente completo para revisión. Lo paso "
            "a validar; la aprobación final queda sujeta a revisión."
        ),
    ),
    TemplateSpec(
        "dinamo_form_pending_v1",
        (
            "También llena este formulario para registrar tus datos: "
            "https://forms.gle/U1MEueL63vgftiuZ8. Cuando lo termines, avísame y "
            "paso tu expediente a revisión."
        ),
    ),
    TemplateSpec(
        "dinamo_audio_processed_v1",
        (
            "Ya tomé lo principal de tu audio. Para avanzar sin confundirnos, solo "
            "confírmame por escrito: {siguiente_pregunta}."
        ),
        ("siguiente_pregunta",),
    ),
    TemplateSpec(
        "dinamo_no_califica_v1",
        (
            "Entendido, por el momento los planes para trabajadores menores a 6 meses "
            "están deshabilitados. Escríbeme cuando cumplas los 6 meses y ese mismo "
            "día te armo tu plan."
        ),
    ),
    TemplateSpec(
        "dinamo_followup_3h_v1",
        (
            "En lugar de gastar en el camión, puedes invertirlo mejor en tu moto. "
            "Aquí estoy para ayudarte con eso."
        ),
    ),
    TemplateSpec(
        "dinamo_followup_12h_v1",
        (
            "Hola, ¿sigues en pie con tu {Moto}? {Plan_Credito_Sentence} "
            "El único paso que falta eres tú."
        ),
        ("Moto", "Plan_Credito_Sentence"),
    ),
    TemplateSpec(
        "dinamo_followup_72h_v1",
        (
            "Te dejo abierto tu avance por aquí. Cuando quieras retomarlo, solo "
            "mándame {Siguiente_Dato_O_Documento}."
        ),
        ("Siguiente_Dato_O_Documento",),
    ),
)


def canonical_field_keys() -> set[str]:
    return {spec.key for spec in FIELD_SPECS}


def build_field_options(spec: FieldSpec) -> dict[str, Any]:
    options: dict[str, Any] = {
        "source": SEED_ID,
        "source_version_id": SOURCE_VERSION_ID,
        "visibility": spec.visibility,
        "aliases": list(spec.aliases),
        "write_owner": spec.write_owner,
        "operator_visible": spec.visibility == "operator",
        "admin_visible": spec.visibility == "admin",
    }
    if spec.choices:
        options["choices"] = list(spec.choices)
    if spec.description:
        options["description"] = spec.description
    if spec.derived_from:
        options["derived_from"] = spec.derived_from
    if spec.key == "Plan_Enganche":
        options["derivation"] = {
            "from_field": "Plan_Credito",
            "map": PLAN_ENGANCHE_BY_PLAN,
            "runtime_owner": "workflow:state.write_contact_field",
        }
    if spec.key == "Moto":
        options["tool_evidence_required"] = ["catalog.search", "quote.resolve"]
    return merge_policy_options(
        options,
        {
            "extractable_by_ai": spec.extractable_by_ai,
            "write_policy": spec.write_policy,
            "confidence_threshold": 0.75 if spec.ai_can_write else 1.0,
            "evidence_required": spec.evidence_required,
            "prompt_visible": spec.visibility == "operator",
            "lifecycle_relevant": spec.key
            in {
                "Cumple_Antiguedad",
                "Plan_Credito",
                "Plan_Enganche",
                "Moto",
                "Cotizacion_Enviada",
                "Doc_Completos",
                "Handoff_Humano",
            },
            "pii": spec.key in {"Banco", "Solicitud_ID", "Google_Drive_File_IDs"},
            "sensitive": spec.visibility == "admin" or spec.key in {"Autorizado"},
        },
    ) or options


def archive_field_options(current: dict[str, Any] | None, *, reason: str) -> dict[str, Any]:
    options = dict(current or {})
    archive = dict(options.get("archived_by_seed") or {})
    archive.update(
        {
            "source": SEED_ID,
            "source_version_id": SOURCE_VERSION_ID,
            "reason": reason,
        }
    )
    options["deprecated"] = True
    options["visibility"] = "admin"
    options["archived_by_seed"] = archive
    return options


def parse_docs_per_plan(requirements: dict[str, Any]) -> dict[str, list[str]]:
    docs_per_plan: dict[str, list[str]] = {}
    for plan in requirements.get("planes") or []:
        if not isinstance(plan, dict) or plan.get("activo") is False:
            continue
        plan_name = str(plan.get("tipo_credito") or "").strip()
        if not plan_name:
            continue
        docs: list[str] = []
        for doc in plan.get("documentos_requeridos") or []:
            if not isinstance(doc, dict):
                continue
            doc_id = str(doc.get("documento_id") or doc.get("doc_id") or "").strip()
            if doc_id and doc_id not in docs:
                docs.append(doc_id)
        docs_per_plan[plan_name] = docs
    return docs_per_plan


def load_requirements(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def build_pipeline_definition(docs_per_plan: dict[str, list[str]]) -> dict[str, Any]:
    return {
        "version": 1,
        "schema": "dinamo_tenant_pipeline_v1",
        "timezone": TENANT_TIMEZONE,
        "metadata": {
            "source": SEED_ID,
            "source_version_id": SOURCE_VERSION_ID,
            "plan_status": PLAN_APPROVAL_STATUS,
            "live_scope": "none",
            "side_effects": "disabled",
        },
        "docs_per_plan": docs_per_plan,
        "fallback": "escalate_to_human",
        "stages": [
            {
                "id": "nuevos",
                "label": "NUEVOS",
                "order": 10,
                "default": True,
                "auto_enter_rules": [],
                "exit_conditions": [
                    {"field": "Cumple_Antiguedad", "operator": "exists"},
                ],
            },
            {
                "id": "plan",
                "label": "PLAN",
                "order": 20,
                "auto_enter_rules": [
                    {"field": "Cumple_Antiguedad", "operator": "equals", "value": True},
                ],
                "exit_conditions": [
                    {"field": "Plan_Credito", "operator": "exists"},
                    {"field": "Plan_Enganche", "operator": "exists"},
                    {"field": "Moto", "operator": "exists"},
                ],
            },
            {
                "id": "cliente_potencial",
                "label": "CLIENTE POTENCIAL",
                "order": 30,
                "auto_enter_rules": [
                    {"field": "Plan_Credito", "operator": "exists"},
                    {"field": "Plan_Enganche", "operator": "exists"},
                    {"field": "Moto", "operator": "exists"},
                    {"field": "Cotizacion_Enviada", "operator": "equals", "value": True},
                ],
            },
            {
                "id": "papeleria_incompleta",
                "label": "PAPELERIA INCOMPLETA",
                "order": 40,
                "auto_enter_rules": [
                    {"field": "Docs_Checklist", "operator": "exists"},
                    {"field": "Doc_Completos", "operator": "equals", "value": False},
                ],
            },
            {
                "id": "papeleria_completa",
                "label": "PAPELERIA COMPLETA",
                "order": 50,
                "auto_enter_rules": [
                    {"field": "Doc_Completos", "operator": "equals", "value": True},
                ],
            },
            {
                "id": "revision_humana",
                "label": "REVISION HUMANA / HANDOFF",
                "order": 60,
                "auto_enter_rules": [],
                "workflow_enter_only": True,
            },
            {
                "id": "no_califica",
                "label": "NO CALIFICA",
                "order": 900,
                "is_terminal": True,
                "auto_enter_rules": [
                    {"field": "Cumple_Antiguedad", "operator": "equals", "value": False},
                ],
            },
            {
                "id": "cerrado_perdido",
                "label": "CERRADO PERDIDO",
                "order": 910,
                "is_terminal": True,
                "auto_enter_rules": [],
                "automation_policy": {"beta": "manual_only"},
            },
            {
                "id": "cerrado_ganado",
                "label": "CERRADO GANADO",
                "order": 920,
                "is_terminal": True,
                "auto_enter_rules": [],
                "automation_policy": {"write_owner": "human_admin_only"},
            },
        ],
    }


def build_tool_binding_specs() -> dict[str, dict[str, Any]]:
    return {
        "catalog.search": {
            "required": True,
            "timeout_ms": 8000,
            "description": (
                "Resolve motorcycle model aliases and categories from the tenant catalog."
            ),
            "metadata_json": {"source": SEED_ID, "fact_only": True, "required_for": ["Moto"]},
        },
        "quote.resolve": {
            "required": True,
            "timeout_ms": 8000,
            "description": "Return exact tenant-approved quote facts for a model and credit plan.",
            "metadata_json": {
                "source": SEED_ID,
                "fact_only": True,
                "required_for": ["Cotizacion_Enviada", "Ultima_Cotizacion"],
            },
        },
        "requirements.lookup": {
            "required": True,
            "timeout_ms": 8000,
            "description": (
                "Return tenant-approved document and eligibility requirements for a plan."
            ),
            "metadata_json": {"source": SEED_ID, "fact_only": True},
        },
        "faq.lookup": {
            "required": False,
            "timeout_ms": 8000,
            "description": "Return tenant-approved FAQ facts for general customer questions.",
            "metadata_json": {"source": SEED_ID, "fact_only": True},
        },
        "document.check": {
            "required": False,
            "timeout_ms": 15000,
            "description": "Classify and review inbound document evidence without customer copy.",
            "metadata_json": {"source": SEED_ID, "fact_only": True, "phase": "E"},
        },
        "expediente.evaluate": {
            "required": False,
            "timeout_ms": 8000,
            "description": "Evaluate dossier completeness for the selected tenant plan.",
            "metadata_json": {"source": SEED_ID, "fact_only": True, "phase": "E"},
        },
        "handoff.request": {
            "required": False,
            "timeout_ms": 5000,
            "description": "Propose an invisible human handoff with a structured reason.",
            "metadata_json": {"source": SEED_ID, "fact_only": True},
        },
        "followup.schedule": {
            "required": False,
            "timeout_ms": 5000,
            "description": "Propose dry-run follow-up scheduling according to tenant policy.",
            "metadata_json": {"source": SEED_ID, "fact_only": True, "phase": "F"},
        },
    }


def build_workflow_specs() -> tuple[WorkflowSpec, ...]:
    return (
        WorkflowSpec(
            key="state.write_contact_field",
            name="Dinamo V1 - State write contact field",
            trigger_type="field_extracted",
            event_type="field_extracted",
            nodes=(
                {
                    "id": "derive_plan_enganche",
                    "type": "condition",
                    "config": {
                        "when": {"field": "Plan_Credito", "operator": "exists"},
                        "derives": {
                            "target_field": "Plan_Enganche",
                            "map": PLAN_ENGANCHE_BY_PLAN,
                        },
                    },
                },
                {
                    "id": "update_plan_enganche",
                    "type": "update_field",
                    "config": {
                        "field": "Plan_Enganche",
                        "value_from": "derived.Plan_Enganche",
                        "write_owner": "system_derived",
                    },
                },
            ),
        ),
        WorkflowSpec(
            key="pipeline.transition",
            name="Dinamo V1 - Pipeline transition",
            trigger_type="field_updated",
            event_type="field_updated",
            nodes=(
                {
                    "id": "move_stage",
                    "type": "move_stage",
                    "config": {
                        "stage_id": "{{ lifecycle.target_stage_id }}",
                        "source": "validated_runtime_event",
                    },
                },
            ),
        ),
        WorkflowSpec(
            key="task.create",
            name="Dinamo V1 - Task create as notification",
            trigger_type="human_handoff_requested",
            event_type="human_handoff_requested",
            nodes=(
                {
                    "id": "notify_francisco",
                    "type": "notify_agent",
                    "config": {
                        "role": "operator",
                        "dedupe_key": "dinamo_task_create:{conversation_id}:{reason}",
                    },
                },
                {
                    "id": "write_reason",
                    "type": "update_field",
                    "config": {"field": "Motivo_Handoff", "value_from": "event.reason"},
                },
            ),
        ),
        WorkflowSpec(
            key="notification.create",
            name="Dinamo V1 - Notification create",
            trigger_type="manual",
            event_type="notification_requested",
            nodes=(
                {
                    "id": "notify_agent",
                    "type": "notify_agent",
                    "config": {
                        "role": "operator",
                        "dedupe_key": "dinamo_notification:{conversation_id}:{event_type}",
                    },
                },
            ),
        ),
        WorkflowSpec(
            key="human.assign",
            name="Dinamo V1 - Human assign",
            trigger_type="human_handoff_requested",
            event_type="human_handoff_requested",
            nodes=(
                {"id": "assign", "type": "assign_agent", "config": {"role": "operator"}},
                {
                    "id": "write_advisor",
                    "type": "update_field",
                    "config": {"field": "Asesor_Asignado", "value": "Francisco"},
                },
            ),
        ),
        WorkflowSpec(
            key="handoff.start",
            name="Dinamo V1 - Handoff start",
            trigger_type="human_handoff_requested",
            event_type="human_handoff_requested",
            nodes=(
                {"id": "assign", "type": "assign_agent", "config": {"role": "operator"}},
                {
                    "id": "notify",
                    "type": "notify_agent",
                    "config": {
                        "role": "operator",
                        "dedupe_key": "dinamo_handoff:{conversation_id}",
                    },
                },
                {"id": "pause_bot", "type": "pause_bot", "config": {"mode": "limited"}},
                {
                    "id": "handoff_flag",
                    "type": "update_field",
                    "config": {"field": "Handoff_Humano", "value": "true"},
                },
                {
                    "id": "handoff_reason",
                    "type": "update_field",
                    "config": {"field": "Motivo_Handoff", "value_from": "event.reason"},
                },
            ),
        ),
        WorkflowSpec(
            key="customer_message.request",
            name="Dinamo V1 - Customer message request",
            trigger_type="manual",
            event_type="customer_message.request",
            customer_message_request_only=True,
            nodes=(
                {
                    "id": "template",
                    "type": "template_message",
                    "config": {
                        "template_source": "tenant_whatsapp_templates",
                        "send_scope": "canonical_send_adapter_only",
                        "dedupe_key": "dinamo_customer_message:{conversation_id}:{case}",
                    },
                },
            ),
        ),
        WorkflowSpec(
            key="followup.schedule",
            name="Dinamo V1 - Followup schedule",
            trigger_type="stage_changed",
            event_type="stage_changed",
            nodes=(
                {
                    "id": "followup",
                    "type": "followup",
                    "config": {
                        "attempt_delays_hours": [3, 12, 72],
                        "quiet_hours": {
                            "timezone": TENANT_TIMEZONE,
                            "start": "23:00",
                            "end": "07:00",
                        },
                        "jitter_minutes": [2, 10],
                        "max_attempts": 3,
                        "cancel_on": [
                            "message_received",
                            "Handoff_Humano",
                            "no_califica",
                            "cerrado_perdido",
                            "cerrado_ganado",
                        ],
                        "templates": [
                            "dinamo_followup_3h_v1",
                            "dinamo_followup_12h_v1",
                            "dinamo_followup_72h_v1",
                        ],
                    },
                },
            ),
        ),
    )


def build_agent_tool_policy_bindings() -> list[dict[str, Any]]:
    bindings: list[dict[str, Any]] = []
    for tool_name, spec in build_tool_binding_specs().items():
        bindings.append(
            {
                "name": tool_name,
                "tool_name": tool_name,
                "description": spec["description"],
                "enabled": True,
                "required": bool(spec["required"]),
                "dry_run_only": True,
                "approval_required": False,
                "input_schema": {"type": "object"},
                "output_facts_schema": {"type": "object"},
                "timeout_ms": spec["timeout_ms"],
                "dry_facts": {
                    "source": SEED_ID,
                    "source_version_id": SOURCE_VERSION_ID,
                    "fact_only": True,
                },
                "metadata": spec["metadata_json"],
            }
        )
    return bindings


def build_agent_field_policy_fields() -> list[dict[str, Any]]:
    fields: list[dict[str, Any]] = []
    for spec in FIELD_SPECS:
        fields.append(
            {
                "field_key": spec.key,
                "key": spec.key,
                "label": spec.label,
                "type": spec.field_type,
                "writable": spec.ai_can_write,
                "required": False,
                "evidence_required": spec.evidence_required,
                "allowed_values": list(spec.choices),
                "allowed_sources": ["customer_message"] if spec.ai_can_write else ["system"],
                "write_policy": spec.write_policy,
                "write_policy_metadata": {
                    "owner": spec.write_owner,
                    "derived_from": spec.derived_from,
                    "tool_evidence_required": ["catalog.search", "quote.resolve"]
                    if spec.key == "Moto"
                    else [],
                },
                "visibility": spec.visibility,
                "source": SEED_ID,
                "source_version_id": SOURCE_VERSION_ID,
            }
        )
    return fields


def build_agent_workflow_policy_bindings() -> list[dict[str, Any]]:
    bindings: list[dict[str, Any]] = []
    for spec in build_workflow_specs():
        bindings.append(
            {
                "binding_name": spec.key,
                "name": spec.key,
                "event_name": spec.event_type,
                "description": spec.name,
                "enabled": True,
                "dry_run_only": True,
                "approval_required": True,
                "side_effects_allowed": False,
                "customer_visible_output_allowed": False,
                "source": SEED_ID,
                "source_version_id": SOURCE_VERSION_ID,
            }
        )
    return bindings


def build_agent_payload() -> dict[str, Any]:
    return {
        "name": AGENT_NAME,
        "role": AGENT_ROLE,
        "tone": "whatsapp_direct",
        "language": "es-MX",
        "instructions": (
            "Identidad: Francisco Esparza, asesor de creditos de Dinamo Monterrey. "
            "Fase A solo prepara configuracion; el prompt conversacional completo "
            "se implementa en Fase C."
        ),
        "prompt_blocks": [
            {
                "id": "dinamo_identity_v1",
                "type": "identity",
                "text": "El agente visible es Francisco Esparza.",
            },
            {
                "id": "dinamo_no_live_boundary_v1",
                "type": "safety",
                "text": "No live send, no outbox, no workflow side effects in Phase A.",
            },
        ],
        "knowledge_policy": {"required_source_ids": [], "phase": "B"},
        "tool_policy": {
            "required_tools": ["catalog.search", "quote.resolve", "requirements.lookup"],
            "bindings": build_agent_tool_policy_bindings(),
        },
        "action_policy": {"execution_mode": "disabled"},
        "field_policy": {
            "source": SEED_ID,
            "source_version_id": SOURCE_VERSION_ID,
            "fields": build_agent_field_policy_fields(),
        },
        "workflow_policy": {
            "execution_mode": "dry_run_only",
            "side_effects_allowed": False,
            "bindings": build_agent_workflow_policy_bindings(),
        },
        "safety_policy": {
            "turn_output_final_message_authority": True,
            "required_tool_failure_means_no_send": True,
        },
        "test_policy": {"required_suite": "dinamo_v1_phase_a_no_send"},
        "snapshot": {"source": SEED_ID, "source_version_id": SOURCE_VERSION_ID, "phase": "A"},
        "change_summary": "Dinamo V1 Phase A seed configuration.",
    }


async def seed_dinamo_v1(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    requirements_path: Path,
    dry_run: bool = False,
) -> SeedResult:
    requirements = load_requirements(requirements_path)
    docs_per_plan = parse_docs_per_plan(requirements)
    result = SeedResult(tenant_id=str(tenant_id), dry_run=dry_run)

    if not dry_run:
        await _seed_fields(session, tenant_id=tenant_id, result=result)
        await _seed_pipeline(
            session,
            tenant_id=tenant_id,
            docs_per_plan=docs_per_plan,
            result=result,
        )
        await _seed_templates(session, tenant_id=tenant_id, result=result)
        agent = await _seed_agent(session, tenant_id=tenant_id, result=result)
        version = await _seed_agent_version(
            session,
            tenant_id=tenant_id,
            agent=agent,
            result=result,
        )
        await _seed_deployment(
            session,
            tenant_id=tenant_id,
            agent=agent,
            version=version,
            result=result,
        )
        workflows = await _seed_workflows(session, tenant_id=tenant_id, result=result)
        await _seed_field_permissions(session, tenant_id=tenant_id, version=version, result=result)
        await _seed_tool_bindings(session, tenant_id=tenant_id, version=version, result=result)
        await _seed_workflow_bindings(
            session,
            tenant_id=tenant_id,
            version=version,
            workflows=workflows,
            result=result,
        )
        await session.flush()
        return result

    result.created_fields = [spec.key for spec in FIELD_SPECS]
    result.pipeline_action = "would_create_or_update"
    result.created_templates = [spec.name for spec in TEMPLATE_SPECS]
    result.created_workflows = [spec.key for spec in build_workflow_specs()]
    result.created_permissions = [spec.key for spec in FIELD_SPECS]
    result.created_tool_bindings = list(build_tool_binding_specs())
    result.created_workflow_bindings = [spec.event_type for spec in build_workflow_specs()]
    result.agent_action = "would_create_or_update"
    result.version_action = "would_create_or_update"
    result.deployment_action = "would_create_or_update_no_send"
    return result


def preview_dinamo_v1_seed(*, tenant_id: UUID) -> SeedResult:
    result = SeedResult(tenant_id=str(tenant_id), dry_run=True)
    result.created_fields = [spec.key for spec in FIELD_SPECS]
    result.pipeline_action = "would_create_or_update"
    result.created_templates = [spec.name for spec in TEMPLATE_SPECS]
    result.created_workflows = [spec.key for spec in build_workflow_specs()]
    result.created_permissions = [spec.key for spec in FIELD_SPECS]
    result.created_tool_bindings = list(build_tool_binding_specs())
    result.created_workflow_bindings = [spec.event_type for spec in build_workflow_specs()]
    result.agent_action = "would_create_or_update"
    result.version_action = "would_create_or_update"
    result.deployment_action = "would_create_or_update_no_send"
    return result


async def _seed_fields(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    result: SeedResult,
) -> None:
    rows = (
        await session.execute(
            select(CustomerFieldDefinition)
            .where(CustomerFieldDefinition.tenant_id == tenant_id)
            .order_by(
                CustomerFieldDefinition.ordering.asc(),
                CustomerFieldDefinition.created_at.asc(),
            )
        )
    ).scalars().all()
    by_key: dict[str, list[CustomerFieldDefinition]] = {}
    for row in rows:
        by_key.setdefault(row.key, []).append(row)

    canonical = canonical_field_keys()
    for key, key_rows in by_key.items():
        if key in canonical:
            for duplicate in key_rows[1:]:
                duplicate.field_options = archive_field_options(
                    duplicate.field_options,
                    reason="duplicate_canonical_field",
                )
                result.archived_fields.append(key)
        else:
            for row in key_rows:
                if not (row.field_options or {}).get("deprecated"):
                    row.field_options = archive_field_options(
                        row.field_options,
                        reason="not_in_dinamo_v1_canonical_fields",
                    )
                    result.archived_fields.append(key)

    for spec in FIELD_SPECS:
        existing = by_key.get(spec.key, [])
        active = next(
            (row for row in existing if not (row.field_options or {}).get("deprecated")),
            None,
        )
        options = build_field_options(spec)
        if active is None:
            session.add(
                CustomerFieldDefinition(
                    tenant_id=tenant_id,
                    key=spec.key,
                    label=spec.label,
                    field_type=spec.field_type,
                    field_options=options,
                    ordering=spec.ordering,
                )
            )
            result.created_fields.append(spec.key)
            continue
        active.label = spec.label
        active.field_type = spec.field_type
        active.field_options = options
        active.ordering = spec.ordering
        result.updated_fields.append(spec.key)


async def _seed_pipeline(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    docs_per_plan: dict[str, list[str]],
    result: SeedResult,
) -> None:
    definition = build_pipeline_definition(docs_per_plan)
    active = (
        await session.execute(
            select(TenantPipeline)
            .where(TenantPipeline.tenant_id == tenant_id, TenantPipeline.active.is_(True))
            .order_by(TenantPipeline.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if active and _is_seeded(active.definition):
        active.definition = definition
        result.pipeline_action = "updated_active_seeded"
        return

    next_version = (
        await session.execute(
            select(func.coalesce(func.max(TenantPipeline.version), 0) + 1).where(
                TenantPipeline.tenant_id == tenant_id
            )
        )
    ).scalar_one()
    if active:
        active.active = False
    session.add(
        TenantPipeline(
            tenant_id=tenant_id,
            version=int(next_version),
            definition=definition,
            active=True,
            history=[],
        )
    )
    result.pipeline_action = "created_new_active"


async def _seed_templates(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    result: SeedResult,
) -> None:
    rows = (
        await session.execute(
            select(WhatsAppTemplate).where(WhatsAppTemplate.tenant_id == tenant_id)
        )
    ).scalars().all()
    by_name = {row.name: row for row in rows}
    for spec in TEMPLATE_SPECS:
        existing = by_name.get(spec.name)
        if existing is None:
            session.add(
                WhatsAppTemplate(
                    tenant_id=tenant_id,
                    name=spec.name,
                    category="utility",
                    status="draft",
                    language="es_MX",
                    body=spec.body,
                    variables=list(spec.variables),
                )
            )
            result.created_templates.append(spec.name)
            continue
        existing.category = "utility"
        existing.status = "draft"
        existing.language = "es_MX"
        existing.body = spec.body
        existing.variables = list(spec.variables)
        result.updated_templates.append(spec.name)


async def _seed_agent(session: AsyncSession, *, tenant_id: UUID, result: SeedResult) -> Agent:
    rows = (
        await session.execute(select(Agent).where(Agent.tenant_id == tenant_id))
    ).scalars().all()
    agent = next(
        (
            row
            for row in rows
            if ((row.ops_config or {}).get(SEED_ID) or {}).get("agent") is True
            or row.name == AGENT_NAME
        ),
        None,
    )
    payload = build_agent_payload()
    ops_config = {
        **(agent.ops_config if agent else {}),
        SEED_ID: {
            "agent": True,
            "source_version_id": SOURCE_VERSION_ID,
            "phase": "A",
            "live_scope": "none",
        },
        "product_first": True,
    }
    if agent is None:
        agent = Agent(
            tenant_id=tenant_id,
            name=payload["name"],
            role=payload["role"],
            status="draft",
            behavior_mode="strict",
            tone=payload["tone"],
            language=payload["language"],
            system_prompt=payload["instructions"],
            is_default=not bool(rows),
            auto_actions={"enabled_action_ids": []},
            knowledge_config=payload["knowledge_policy"],
            extraction_config={"visible_contact_field_keys": [spec.key for spec in FIELD_SPECS]},
            flow_mode_rules=_allowed_stage_rules(),
            ops_config=ops_config,
        )
        session.add(agent)
        await session.flush()
        result.agent_action = "created"
        return agent
    agent.name = payload["name"]
    agent.role = payload["role"]
    agent.status = "draft"
    agent.behavior_mode = "strict"
    agent.tone = payload["tone"]
    agent.language = payload["language"]
    agent.system_prompt = payload["instructions"]
    agent.knowledge_config = payload["knowledge_policy"]
    agent.extraction_config = {"visible_contact_field_keys": [spec.key for spec in FIELD_SPECS]}
    agent.flow_mode_rules = _allowed_stage_rules()
    agent.ops_config = ops_config
    result.agent_action = "updated"
    return agent


async def _seed_agent_version(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    agent: Agent,
    result: SeedResult,
) -> AgentVersion:
    versions = (
        await session.execute(
            select(AgentVersion)
            .where(AgentVersion.tenant_id == tenant_id, AgentVersion.agent_id == agent.id)
            .order_by(AgentVersion.version_number.desc())
        )
    ).scalars().all()
    version = next(
        (
            row
            for row in versions
            if row.status == "draft" and (row.snapshot or {}).get("source") == SEED_ID
        ),
        None,
    )
    payload = build_agent_payload()
    if version is None:
        next_version = max([row.version_number for row in versions] or [0]) + 1
        version = AgentVersion(
            tenant_id=tenant_id,
            agent_id=agent.id,
            version_number=next_version,
            status="draft",
            is_immutable=False,
            role=payload["role"],
            tone=payload["tone"],
            language=payload["language"],
            instructions=payload["instructions"],
            prompt_blocks=payload["prompt_blocks"],
            knowledge_policy=payload["knowledge_policy"],
            tool_policy=payload["tool_policy"],
            action_policy=payload["action_policy"],
            field_policy=payload["field_policy"],
            workflow_policy=payload["workflow_policy"],
            safety_policy=payload["safety_policy"],
            test_policy=payload["test_policy"],
            snapshot=payload["snapshot"],
            change_summary=payload["change_summary"],
        )
        session.add(version)
        await session.flush()
        result.version_action = "created"
        return version
    version.role = payload["role"]
    version.tone = payload["tone"]
    version.language = payload["language"]
    version.instructions = payload["instructions"]
    version.prompt_blocks = payload["prompt_blocks"]
    version.knowledge_policy = payload["knowledge_policy"]
    version.tool_policy = payload["tool_policy"]
    version.action_policy = payload["action_policy"]
    version.field_policy = payload["field_policy"]
    version.workflow_policy = payload["workflow_policy"]
    version.safety_policy = payload["safety_policy"]
    version.test_policy = payload["test_policy"]
    version.snapshot = payload["snapshot"]
    version.change_summary = payload["change_summary"]
    result.version_action = "updated"
    return version


async def _seed_deployment(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    agent: Agent,
    version: AgentVersion,
    result: SeedResult,
) -> None:
    deployment = (
        await session.execute(
            select(AgentDeployment).where(
                AgentDeployment.tenant_id == tenant_id,
                AgentDeployment.agent_id == agent.id,
                AgentDeployment.channel == "test_lab",
                AgentDeployment.environment == "no_send",
            )
        )
    ).scalar_one_or_none()
    metadata = {
        "source": SEED_ID,
        "source_version_id": SOURCE_VERSION_ID,
        "phase": "A",
        "approved_beta_contact": "+528128889241",
        "live_scope": "none",
    }
    if deployment is None:
        session.add(
            AgentDeployment(
                tenant_id=tenant_id,
                agent_id=agent.id,
                active_version_id=version.id,
                name="Dinamo V1 no-send",
                channel="test_lab",
                environment="no_send",
                publish_state="draft",
                runtime_mode="no_send",
                send_scope="none",
                send_enabled=False,
                outbox_enabled=False,
                live_send_enabled=False,
                single_contact_smoke_enabled=False,
                actions_enabled=False,
                workflow_events_enabled=False,
                workflow_side_effects_enabled=False,
                canary_enabled=False,
                open_production_enabled=False,
                metadata_json=metadata,
            )
        )
        result.deployment_action = "created_no_send"
        return
    deployment.active_version_id = version.id
    deployment.name = "Dinamo V1 no-send"
    deployment.publish_state = "draft"
    deployment.runtime_mode = "no_send"
    deployment.send_scope = "none"
    deployment.send_enabled = False
    deployment.outbox_enabled = False
    deployment.live_send_enabled = False
    deployment.single_contact_smoke_enabled = False
    deployment.actions_enabled = False
    deployment.workflow_events_enabled = False
    deployment.workflow_side_effects_enabled = False
    deployment.canary_enabled = False
    deployment.open_production_enabled = False
    deployment.metadata_json = metadata
    result.deployment_action = "updated_no_send"


async def _seed_workflows(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    result: SeedResult,
) -> dict[str, Workflow]:
    rows = (
        await session.execute(select(Workflow).where(Workflow.tenant_id == tenant_id))
    ).scalars().all()
    workflows_by_key = {
        ((row.definition or {}).get("metadata") or {}).get("workflow_key"): row
        for row in rows
        if ((row.definition or {}).get("metadata") or {}).get("source") == SEED_ID
    }
    seeded: dict[str, Workflow] = {}
    for spec in build_workflow_specs():
        definition = {
            "nodes": list(copy.deepcopy(spec.nodes)),
            "edges": list(copy.deepcopy(spec.edges)),
            "metadata": {
                "source": SEED_ID,
                "source_version_id": SOURCE_VERSION_ID,
                "workflow_key": spec.key,
                "status": "draft",
                "side_effects": "disabled",
                "customer_message_request_only": spec.customer_message_request_only,
            },
        }
        trigger_config = {
            "source": SEED_ID,
            "source_version_id": SOURCE_VERSION_ID,
            "event_type": spec.event_type,
            "dry_run_only": True,
        }
        existing = workflows_by_key.get(spec.key)
        if existing is None:
            existing = Workflow(
                tenant_id=tenant_id,
                name=spec.name,
                description="Dinamo V1 Phase A draft workflow. Side effects disabled.",
                trigger_type=spec.trigger_type,
                trigger_config=trigger_config,
                definition=definition,
                active=False,
            )
            session.add(existing)
            await session.flush()
            result.created_workflows.append(spec.key)
        else:
            existing.name = spec.name
            existing.description = "Dinamo V1 Phase A draft workflow. Side effects disabled."
            existing.trigger_type = spec.trigger_type
            existing.trigger_config = trigger_config
            existing.definition = definition
            existing.active = False
            result.updated_workflows.append(spec.key)
        seeded[spec.key] = existing
    return seeded


async def _seed_field_permissions(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    version: AgentVersion,
    result: SeedResult,
) -> None:
    rows = (
        await session.execute(
            select(AgentFieldPermission).where(
                AgentFieldPermission.tenant_id == tenant_id,
                AgentFieldPermission.agent_version_id == version.id,
            )
        )
    ).scalars().all()
    by_key = {row.field_key: row for row in rows}
    for spec in FIELD_SPECS:
        metadata = {
            "source": SEED_ID,
            "source_version_id": SOURCE_VERSION_ID,
            "write_owner": spec.write_owner,
            "derived_from": spec.derived_from,
        }
        write_policy = {
            "owner": spec.write_owner,
            "tool_evidence_required": ["catalog.search", "quote.resolve"]
            if spec.key == "Moto"
            else [],
        }
        existing = by_key.get(spec.key)
        if existing is None:
            session.add(
                AgentFieldPermission(
                    tenant_id=tenant_id,
                    agent_version_id=version.id,
                    field_key=spec.key,
                    can_read=True,
                    can_write=spec.ai_can_write,
                    evidence_required=spec.evidence_required,
                    write_policy=write_policy,
                    metadata_json=metadata,
                )
            )
            result.created_permissions.append(spec.key)
            continue
        existing.can_read = True
        existing.can_write = spec.ai_can_write
        existing.evidence_required = spec.evidence_required
        existing.write_policy = write_policy
        existing.metadata_json = metadata
        result.updated_permissions.append(spec.key)


async def _seed_tool_bindings(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    version: AgentVersion,
    result: SeedResult,
) -> None:
    rows = (
        await session.execute(
            select(AgentToolBinding).where(
                AgentToolBinding.tenant_id == tenant_id,
                AgentToolBinding.agent_version_id == version.id,
            )
        )
    ).scalars().all()
    by_name = {row.tool_name: row for row in rows}
    for tool_name, spec in build_tool_binding_specs().items():
        existing = by_name.get(tool_name)
        if existing is None:
            session.add(
                AgentToolBinding(
                    tenant_id=tenant_id,
                    agent_version_id=version.id,
                    tool_name=tool_name,
                    enabled=True,
                    required=bool(spec["required"]),
                    input_schema={"type": "object"},
                    output_schema={"type": "object"},
                    timeout_ms=spec["timeout_ms"],
                    metadata_json=spec["metadata_json"],
                )
            )
            result.created_tool_bindings.append(tool_name)
            continue
        existing.enabled = True
        existing.required = bool(spec["required"])
        existing.input_schema = {"type": "object"}
        existing.output_schema = {"type": "object"}
        existing.timeout_ms = spec["timeout_ms"]
        existing.metadata_json = spec["metadata_json"]
        result.updated_tool_bindings.append(tool_name)


async def _seed_workflow_bindings(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    version: AgentVersion,
    workflows: dict[str, Workflow],
    result: SeedResult,
) -> None:
    rows = (
        await session.execute(
            select(AgentWorkflowBinding).where(
                AgentWorkflowBinding.tenant_id == tenant_id,
                AgentWorkflowBinding.agent_version_id == version.id,
            )
        )
    ).scalars().all()
    by_key = {
        (str(row.workflow_id), row.event_type): row
        for row in rows
    }
    specs = {spec.key: spec for spec in build_workflow_specs()}
    for key, workflow in workflows.items():
        spec = specs[key]
        binding_key = (str(workflow.id), spec.event_type)
        metadata = {
            "source": SEED_ID,
            "source_version_id": SOURCE_VERSION_ID,
            "workflow_key": key,
            "customer_message_request_only": spec.customer_message_request_only,
        }
        existing = by_key.get(binding_key)
        if existing is None:
            session.add(
                AgentWorkflowBinding(
                    tenant_id=tenant_id,
                    agent_version_id=version.id,
                    workflow_id=workflow.id,
                    event_type=spec.event_type,
                    enabled=True,
                    execution_mode="dry_run_only",
                    side_effects_allowed=False,
                    customer_visible_output_allowed=False,
                    metadata_json=metadata,
                )
            )
            result.created_workflow_bindings.append(spec.event_type)
            continue
        existing.enabled = True
        existing.execution_mode = "dry_run_only"
        existing.side_effects_allowed = False
        existing.customer_visible_output_allowed = False
        existing.metadata_json = metadata
        result.updated_workflow_bindings.append(spec.event_type)


def _is_seeded(definition: dict[str, Any] | None) -> bool:
    return ((definition or {}).get("metadata") or {}).get("source") == SEED_ID


def _allowed_stage_rules() -> dict[str, list[str]]:
    return {
        "allowed_stage_ids": [
            stage["id"] for stage in build_pipeline_definition({})["stages"]
        ],
    }


async def _main(tenant_id: UUID, requirements_path: Path, dry_run: bool) -> int:
    if dry_run:
        load_requirements(requirements_path)
        result = preview_dinamo_v1_seed(tenant_id=tenant_id)
        print(json.dumps(result.as_dict(), indent=2, ensure_ascii=False))
        print(f"completed_at={datetime.now(UTC).isoformat()}")
        return 0

    from atendia.db.session import _get_factory  # type: ignore[attr-defined]

    factory = _get_factory()
    async with factory() as session:
        result = await seed_dinamo_v1(
            session,
            tenant_id=tenant_id,
            requirements_path=requirements_path,
            dry_run=dry_run,
        )
        await session.commit()
    print(json.dumps(result.as_dict(), indent=2, ensure_ascii=False))
    print(f"completed_at={datetime.now(UTC).isoformat()}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-id", type=UUID, required=True)
    parser.add_argument(
        "--requirements-path",
        type=Path,
        default=DEFAULT_REQUIREMENTS_PATH,
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    return asyncio.run(_main(args.tenant_id, args.requirements_path, args.dry_run))


if __name__ == "__main__":
    sys.exit(main())
