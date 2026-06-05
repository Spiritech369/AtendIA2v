# ruff: noqa: E501,E402

from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
import sys
import zipfile
from pathlib import Path
from typing import Any
from uuid import UUID, uuid5
from xml.etree import ElementTree

from sqlalchemy import text

REPO_ROOT = Path(__file__).resolve().parents[1]
CORE_DIR = REPO_ROOT / "core"
if str(CORE_DIR) not in sys.path:
    sys.path.insert(0, str(CORE_DIR))

from atendia.contracts.pipeline_definition import PipelineDefinition
from atendia.db.session import _get_factory

EMAIL = "dinamomotosnl@gmail.com"
TENANT_ID = UUID("6ad78236-1fc9-467a-858d-90d248d57ee5")
SETUP_KEY = "dinamo_fresh_tenant_v1"
TODAY = "2026_06_02"
NS = UUID("ea9472f6-2166-4f1c-bcae-0849fd487c44")

SOURCE_FILES = {
    "catalogo_dinamo.docx": "ATENDIA_DINAMO_Catalogo_KB_IA.docx",
    "requisitos_dinamo.docx": "ATENDIA_DINAMO_Requisitos_KB_IA.docx",
    "faq_dinamo.docx": "ATENDIA_DINAMO_FAQ_KB_IA.docx",
    "prompt_agente_dinamo.txt": "Prompt Agente IA.txt",
    "flujo_dinamo_orden_caos.docx": "Flujo_Dinamo_Orden_y_Caos.docx",
}

JSON_SOURCES = {
    "catalogo_dinamo_json": "CatalogoMotos2026_DINAMO.json",
    "requisitos_dinamo_json": "Requisitos_Credito_Dinamo.json",
    "faq_dinamo_json": "FAQ_DINAMO.json",
}

FIELD_KEYS = [
    "Cumple_Antiguedad",
    "Plan_Credito",
    "Plan_Enganche",
    "Moto",
    "Doc_Incompletos",
    "Doc_Completos",
    "Autorizado",
    "Cotizacion_Enviada",
    "Ultima_Cotizacion",
    "Docs_Checklist",
    "Handoff_Humano",
]

PLAN_TO_ENGANCHE = {
    "Nomina Tarjeta": "10%",
    "Nomina Recibos": "15%",
    "Pensionado": "10%",
    "Negocio SAT": "15%",
    "Sin Comprobantes": "20%",
    "Guardia": "30%",
    "Contado": "100%",
}

DOCUMENT_RULES = {
    "Nomina Tarjeta": [
        "INE_AMBOS_LADOS",
        "COMPROBANTE_DOMICILIO",
        "ESTADOS_CUENTA_2_MESES",
        "NOMINA_1_MES_DENTRO_ESTADO_CUENTA",
    ],
    "Nomina Recibos": [
        "INE_AMBOS_LADOS",
        "COMPROBANTE_DOMICILIO",
        "RECIBOS_NOMINA_2_MESES",
    ],
    "Pensionado": [
        "INE_AMBOS_LADOS",
        "COMPROBANTE_DOMICILIO",
        "ESTADOS_CUENTA_2_MESES_PENSION",
        "CARTA_RESOLUCION_IMSS",
    ],
    "Negocio SAT": [
        "INE_AMBOS_LADOS",
        "COMPROBANTE_DOMICILIO",
        "CONSTANCIA_SITUACION_FISCAL",
        "FACTURA_TICKET_INSUMO_RECIENTE",
    ],
    "Sin Comprobantes": ["INE_AMBOS_LADOS", "COMPROBANTE_DOMICILIO"],
    "Guardia": [
        "INE_AMBOS_LADOS",
        "COMPROBANTE_DOMICILIO",
        "ESTADOS_CUENTA_2_MESES",
        "NOMINA_1_MES_DENTRO_ESTADO_CUENTA",
    ],
    "Contado": [],
}

DOC_LABELS = {
    "INE_AMBOS_LADOS": "INE ambos lados",
    "COMPROBANTE_DOMICILIO": "Comprobante de domicilio",
    "ESTADOS_CUENTA_2_MESES": "Estados de cuenta 2 meses",
    "NOMINA_1_MES_DENTRO_ESTADO_CUENTA": "Nomina 1 mes dentro de estado de cuenta",
    "RECIBOS_NOMINA_2_MESES": "Recibos de nomina 2 meses",
    "ESTADOS_CUENTA_2_MESES_PENSION": "Estados de cuenta 2 meses pension",
    "CARTA_RESOLUCION_IMSS": "Carta resolucion IMSS",
    "CONSTANCIA_SITUACION_FISCAL": "Constancia de situacion fiscal",
    "FACTURA_TICKET_INSUMO_RECIENTE": "Factura o ticket de insumo reciente",
}


def uid(name: str) -> UUID:
    return uuid5(NS, f"{TENANT_ID}:{SETUP_KEY}:{name}")


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def docx_text(path: Path) -> str:
    with zipfile.ZipFile(path) as zf:
        xml = zf.read("word/document.xml")
    root = ElementTree.fromstring(xml)
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    paragraphs: list[str] = []
    for paragraph in root.findall(".//w:p", ns):
        text_parts = [node.text or "" for node in paragraph.findall(".//w:t", ns)]
        line = "".join(text_parts).strip()
        if line:
            paragraphs.append(line)
    return "\n".join(paragraphs)


def source_text(path: Path) -> str:
    if path.suffix.lower() == ".docx":
        return docx_text(path)
    return path.read_text(encoding="utf-8", errors="ignore")


def chunk_text(value: str, *, size: int = 2200) -> list[str]:
    normalized = "\n".join(line.rstrip() for line in value.splitlines()).strip()
    if not normalized:
        return []
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for paragraph in normalized.split("\n"):
        part = paragraph.strip()
        if not part:
            continue
        if current and current_len + len(part) + 1 > size:
            chunks.append("\n".join(current))
            current = []
            current_len = 0
        current.append(part)
        current_len += len(part) + 1
    if current:
        chunks.append("\n".join(current))
    return chunks


def normalize_sources() -> dict[str, dict[str, Any]]:
    target_dir = REPO_ROOT / "docs" / "tenant_sources" / "dinamo"
    target_dir.mkdir(parents=True, exist_ok=True)
    report: dict[str, dict[str, Any]] = {}
    for normalized, source_name in SOURCE_FILES.items():
        source = REPO_ROOT / "docs" / source_name
        if not source.exists():
            raise FileNotFoundError(source)
        target = target_dir / normalized
        shutil.copy2(source, target)
        report[normalized] = {
            "source": str(source.relative_to(REPO_ROOT)).replace("\\", "/"),
            "target": str(target.relative_to(REPO_ROOT)).replace("\\", "/"),
            "sha256": sha256(target),
            "bytes": target.stat().st_size,
        }
    for key, source_name in JSON_SOURCES.items():
        source = REPO_ROOT / "docs" / source_name
        target = target_dir / source_name
        if source.exists():
            shutil.copy2(source, target)
            report[key] = {
                "source": str(source.relative_to(REPO_ROOT)).replace("\\", "/"),
                "target": str(target.relative_to(REPO_ROOT)).replace("\\", "/"),
                "sha256": sha256(target),
                "bytes": target.stat().st_size,
            }
    return report


def field_options(
    *,
    extractable_by_ai: bool,
    write_policy: str,
    confidence_threshold: float = 0.85,
    evidence_required: bool = True,
    prompt_visible: bool = True,
    lifecycle_relevant: bool = True,
    choices: list[str] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    contact_memory_write_policy = (
        write_policy if write_policy in {"ai_auto", "ai_suggest", "human_only"} else "human_only"
    )
    options: dict[str, Any] = {
        "contact_memory": {
            "extractable_by_ai": extractable_by_ai,
            "write_policy": contact_memory_write_policy,
            "confidence_threshold": confidence_threshold,
            "evidence_required": evidence_required,
            "prompt_visible": prompt_visible,
            "lifecycle_relevant": lifecycle_relevant,
            "pii": False,
            "sensitive": False,
        },
        "declared_write_policy": write_policy,
        **extra,
    }
    if choices:
        options["choices"] = choices
    return options


def contact_fields() -> list[dict[str, Any]]:
    return [
        {
            "key": "Cumple_Antiguedad",
            "label": "Cumple Antiguedad",
            "field_type": "checkbox",
            "ordering": 10,
            "field_options": field_options(
                extractable_by_ai=True,
                write_policy="ai_auto",
                nullable_semantics={"null": "desconocido", "true": "6 meses o mas", "false": "menos de 6 meses"},
            ),
        },
        {
            "key": "Plan_Credito",
            "label": "Plan Credito",
            "field_type": "select",
            "ordering": 20,
            "field_options": field_options(
                extractable_by_ai=True,
                write_policy="ai_auto",
                choices=list(PLAN_TO_ENGANCHE),
                assignment_rules={
                    "Nomina Tarjeta": "ingresos en tarjeta/banco",
                    "Nomina Recibos": "recibos de nomina aunque paguen efectivo",
                    "Pensionado": "pensionado IMSS",
                    "Negocio SAT": "negocio registrado SAT/RIF",
                    "Sin Comprobantes": "efectivo por fuera o sin comprobantes",
                    "Guardia": "guardia de seguridad",
                    "Contado": "compra directa sin credito",
                },
            ),
        },
        {
            "key": "Plan_Enganche",
            "label": "Plan Enganche",
            "field_type": "select",
            "ordering": 30,
            "field_options": field_options(
                extractable_by_ai=False,
                write_policy="system_derived",
                choices=["10%", "15%", "20%", "30%", "100%"],
                derived_from="Plan_Credito",
                derivation_map=PLAN_TO_ENGANCHE,
            ),
        },
        {
            "key": "Moto",
            "label": "Moto",
            "field_type": "catalog_item",
            "ordering": 40,
            "field_options": field_options(
                extractable_by_ai=True,
                write_policy="ai_auto",
                validation="must_exist_in_catalogo_dinamo",
            ),
        },
        {
            "key": "Doc_Incompletos",
            "label": "Doc Incompletos",
            "field_type": "text",
            "ordering": 50,
            "field_options": field_options(
                extractable_by_ai=False,
                write_policy="system_derived",
                derived_from="Docs_Checklist",
            ),
        },
        {
            "key": "Doc_Completos",
            "label": "Doc Completos",
            "field_type": "checkbox",
            "ordering": 60,
            "field_options": field_options(
                extractable_by_ai=False,
                write_policy="system_derived",
                completion_rule="all_required_documents_accepted",
            ),
        },
        {
            "key": "Autorizado",
            "label": "Autorizado",
            "field_type": "checkbox",
            "ordering": 70,
            "field_options": field_options(
                extractable_by_ai=False,
                write_policy="human_only",
                evidence_required=False,
                lifecycle_relevant=False,
            ),
        },
        {
            "key": "Cotizacion_Enviada",
            "label": "Cotizacion Enviada",
            "field_type": "checkbox",
            "ordering": 80,
            "field_options": field_options(
                extractable_by_ai=False,
                write_policy="system_derived",
                derived_from="QuoteResolver",
                technical_section="Tecnicos",
            ),
        },
        {
            "key": "Ultima_Cotizacion",
            "label": "Ultima Cotizacion",
            "field_type": "text",
            "ordering": 90,
            "field_options": field_options(
                extractable_by_ai=False,
                write_policy="system_derived",
                render_mode="quote_card",
                value_format="json",
                technical_section="Tecnicos",
            ),
        },
        {
            "key": "Docs_Checklist",
            "label": "Docs Checklist",
            "field_type": "text",
            "ordering": 100,
            "field_options": field_options(
                extractable_by_ai=False,
                write_policy="system_derived",
                render_mode="document_checklist",
                value_format="json",
                status_values=["pending", "received", "accepted", "rejected", "needs_review", "not_applicable"],
                technical_section="Tecnicos",
            ),
        },
        {
            "key": "Handoff_Humano",
            "label": "Handoff Humano",
            "field_type": "checkbox",
            "ordering": 110,
            "field_options": field_options(
                extractable_by_ai=False,
                write_policy="system_or_workflow",
                lifecycle_relevant=False,
                technical_section="Tecnicos",
            ),
        },
    ]


def pipeline_definition() -> dict[str, Any]:
    documents_catalog = [
        {"key": key, "label": DOC_LABELS[key], "hint": "Documento requerido por plan"}
        for key in DOC_LABELS
    ]
    definition = {
        "version": 1,
        "nlu": {"history_turns": 4},
        "composer": {"history_turns": 4},
        "fallback": "escalate_to_human",
        "document_requirements_field": "Plan_Credito",
        "document_requirements": DOCUMENT_RULES,
        "selection_catalog": {
            plan: {
                "label": plan,
                "plan_enganche": PLAN_TO_ENGANCHE[plan],
                "documents": DOCUMENT_RULES[plan],
            }
            for plan in DOCUMENT_RULES
        },
        "documents_catalog": documents_catalog,
        "vision_doc_mapping": {
            "INE": ["DOCS_INE_AMBOS_LADOS"],
            "COMPROBANTE_DOMICILIO": ["DOCS_COMPROBANTE_DOMICILIO"],
            "ESTADO_CUENTA": ["DOCS_ESTADOS_CUENTA_2_MESES"],
            "NOMINA": ["DOCS_NOMINA_1_MES_DENTRO_ESTADO_CUENTA", "DOCS_RECIBOS_NOMINA_2_MESES"],
        },
        "mode_labels": {
            "PLAN": "Plan",
            "SALES": "Cotizacion",
            "DOC": "Papeleria",
            "OBSTACLE": "Objeciones",
            "RETENTION": "Seguimiento",
            "SUPPORT": "Soporte",
        },
        "mode_prompts": {
            "PLAN": "Identifica antiguedad, metodo de ingresos y Plan_Credito. Una pregunta por turno.",
            "SALES": "Resuelve modelo y cotizacion solo con Knowledge OS y catalogo comercial.",
            "DOC": "Pide solo documentos faltantes del Plan_Credito activo.",
            "OBSTACLE": "Responde objeciones sin prometer aprobacion.",
            "RETENTION": "Da seguimiento breve y no recotices sin cambio de contexto.",
            "SUPPORT": "Responde dudas generales con FAQ o escala si falta fuente.",
        },
        "payload_resolvers": [
            {
                "id": "quote_resolver_dinamo_preview",
                "type": "quote",
                "requires": ["Moto", "Plan_Credito", "Plan_Enganche"],
                "catalog_source_key": "catalogo_dinamo",
                "block_placeholders": ["$X", "$Y", "$Z", "{precio}", "{enganche}", "{pago}", "N quincenas", "TBD", "placeholder"],
                "write_fields": ["Cotizacion_Enviada", "Ultima_Cotizacion"],
                "execution_mode": "preview_only",
            },
            {
                "id": "docs_checklist_resolver_dinamo_preview",
                "type": "document_checklist",
                "requires": ["Plan_Credito"],
                "document_requirements_field": "Plan_Credito",
                "write_fields": ["Docs_Checklist", "Doc_Incompletos", "Doc_Completos"],
                "execution_mode": "preview_only",
            },
        ],
        "stages": [
            {
                "id": "nuevos",
                "label": "Nuevos",
                "manual": False,
                "default": True,
                "behavior_mode": "PLAN",
                "actions_allowed": ["ask_field", "lookup_faq", "search_catalog"],
                "transitions": [
                    {"to": "galgo", "when": "Cumple_Antiguedad=false"},
                    {"to": "plan", "when": "Plan_Credito and Plan_Enganche exist"},
                ],
            },
            {
                "id": "plan",
                "label": "Plan",
                "manual": False,
                "behavior_mode": "PLAN",
                "actions_allowed": ["ask_field", "search_catalog", "quote"],
                "auto_enter_rules": {
                    "enabled": True,
                    "match": "all",
                    "conditions": [
                        {"field": "Plan_Credito", "operator": "exists"},
                        {"field": "Plan_Enganche", "operator": "exists"},
                    ],
                },
                "transitions": [{"to": "cliente_potencial", "when": "Cotizacion_Enviada=true"}],
            },
            {
                "id": "cliente_potencial",
                "label": "Cliente Potencial",
                "manual": False,
                "behavior_mode": "SALES",
                "actions_allowed": ["lookup_faq", "quote", "ask_field"],
                "auto_enter_rules": {
                    "enabled": True,
                    "match": "all",
                    "conditions": [
                        {"field": "Plan_Credito", "operator": "exists"},
                        {"field": "Plan_Enganche", "operator": "exists"},
                        {"field": "Moto", "operator": "exists"},
                        {"field": "Cotizacion_Enviada", "operator": "equals", "value": "true"},
                    ],
                },
                "transitions": [{"to": "papeleria_incompleta", "when": "real document received"}],
            },
            {
                "id": "papeleria_incompleta",
                "label": "Papeleria Incompleta",
                "manual": False,
                "behavior_mode": "DOC",
                "actions_allowed": ["ask_field", "lookup_requirements"],
                "auto_enter_rules": {
                    "enabled": True,
                    "match": "all",
                    "conditions": [
                        {"field": "Docs_Checklist", "operator": "exists"},
                        {"field": "Doc_Completos", "operator": "equals", "value": "false"},
                    ],
                },
                "transitions": [{"to": "papeleria_completa", "when": "Doc_Completos=true"}],
            },
            {
                "id": "papeleria_completa",
                "label": "Papeleria Completa",
                "manual": False,
                "behavior_mode": "DOC",
                "actions_allowed": ["escalate_to_human"],
                "auto_enter_rules": {
                    "enabled": True,
                    "match": "all",
                    "conditions": [
                        {"field": "Doc_Completos", "operator": "equals", "value": "true"},
                    ],
                },
                "pause_bot_on_enter": False,
                "handoff_reason": "documents_complete_review",
            },
            {
                "id": "galgo",
                "label": "Galgo",
                "manual": False,
                "behavior_mode": "SUPPORT",
                "actions_allowed": ["close"],
                "auto_enter_rules": {
                    "enabled": True,
                    "match": "all",
                    "conditions": [
                        {"field": "Cumple_Antiguedad", "operator": "equals", "value": "false"},
                    ],
                },
                "is_terminal": True,
            },
            {
                "id": "sistema",
                "label": "Sistema",
                "manual": True,
                "behavior_mode": "SUPPORT",
                "actions_allowed": [],
                "is_terminal": True,
            },
            {
                "id": "cliente_cerrado",
                "label": "Cliente Cerrado",
                "manual": True,
                "behavior_mode": "SUPPORT",
                "actions_allowed": [],
                "is_terminal": True,
            },
        ],
    }
    PipelineDefinition.model_validate(definition)
    return definition


def mandatory_instructions(prompt_text: str) -> str:
    rules = """
Eres Francisco Esparza, asesor de creditos de motocicletas en Dinamo Monterrey.
Responde siempre en espanol, tono informal, directo y de WhatsApp. No uses emojis.
Maximo 2 frases normales. Si el cliente hace varias preguntas, responde todas breve y luego haz una sola pregunta de avance.
No suenes a formulario. Responde primero la duda actual.
Usa solo Knowledge OS para catalogo, requisitos y FAQ.
No inventes modelos, precios, enganches, pagos, quincenas, promociones, disponibilidad, aprobacion, horarios ni direccion.
No prometas aprobacion.
No pidas documentos antes de cotizar, salvo que el cliente ya haya enviado un documento; en ese caso reconocelo y regresa al dato faltante.
Flujo comercial recomendado para credito: Antiguedad, Moto de interes, Metodo de ingresos / Plan_Credito, Cotizacion, Documentos del plan, Revision humana.
El cliente puede dar datos en otro orden; guarda lo que diga y pide solo el siguiente faltante.
Si Cumple_Antiguedad=false, mover a Galgo y cerrar amablemente.
Si Plan_Credito=Contado, no seguir flujo de credito; cotiza contado y mover a Cliente Potencial.
Si Plan_Credito + Moto existen, cotizar con QuoteResolver.
Despues de cotizar, si el cliente quiere avanzar, pedir documentos del plan.
Pedir solo documentos faltantes.
Si Doc_Completos=true, activar Handoff_Humano por workflow.
Si cliente pide humano, activar Handoff_Humano.
Autorizado es manual; la IA nunca lo escribe.
El unico mensaje visible al cliente debe salir de TurnOutput.final_message.
No habilitar flujo_dinamo_orden_caos ni prompt_agente_dinamo como KB factual para respuesta al cliente.
"""
    return (prompt_text.strip() + "\n\n---\nReglas oficiales tenant-scoped:\n" + rules.strip()).strip()


def workflow_rows() -> list[dict[str, Any]]:
    return [
        {
            "id": uid("workflow_doc_completos_handoff"),
            "name": "workflow_doc_completos_handoff",
            "description": "Draft disabled: handoff when Doc_Completos=true.",
            "trigger_type": "field_updated",
            "trigger_config": {"field_key": "Doc_Completos", "value": True, "mode": "preview_only"},
            "definition": {
                "status": "draft",
                "real_send_enabled": False,
                "nodes": [
                    {"id": "trigger", "type": "trigger", "label": "Doc_Completos true"},
                    {"id": "set_handoff", "type": "set_field", "field_key": "Handoff_Humano", "value": True},
                    {"id": "note", "type": "internal_note", "text": "Papeleria completa, requiere revision humana"},
                    {
                        "id": "prepare_message",
                        "type": "prepare_message",
                        "text": "Listo, recibi tu papeleria completa. La paso a revision y en 24 horas habiles te damos respuesta.",
                    },
                ],
                "edges": [
                    {"from": "trigger", "to": "set_handoff"},
                    {"from": "set_handoff", "to": "note"},
                    {"from": "note", "to": "prepare_message"},
                ],
            },
        },
        {
            "id": uid("workflow_galgo_close"),
            "name": "workflow_galgo_close",
            "description": "Draft disabled: close when Cumple_Antiguedad=false or stage galgo.",
            "trigger_type": "field_updated",
            "trigger_config": {"field_key": "Cumple_Antiguedad", "value": False, "mode": "preview_only"},
            "definition": {
                "status": "draft",
                "real_send_enabled": False,
                "nodes": [
                    {"id": "trigger", "type": "trigger", "label": "Antiguedad insuficiente"},
                    {
                        "id": "prepare_message",
                        "type": "prepare_message",
                        "text": "Por ahora para credito necesitamos minimo 6 meses de antiguedad. Si mas adelante cumples ese tiempo, con gusto lo revisamos.",
                    },
                    {"id": "close", "type": "close_conversation", "enabled": False},
                ],
                "edges": [
                    {"from": "trigger", "to": "prepare_message"},
                    {"from": "prepare_message", "to": "close"},
                ],
            },
        },
        {
            "id": uid("workflow_cliente_cerrado_manual"),
            "name": "workflow_cliente_cerrado_manual",
            "description": "Manual only. No automation.",
            "trigger_type": "manual_only",
            "trigger_config": {"stage_id": "cliente_cerrado"},
            "definition": {"status": "draft", "nodes": [], "edges": [], "real_send_enabled": False},
        },
        {
            "id": uid("workflow_sistema_manual"),
            "name": "workflow_sistema_manual",
            "description": "Manual only. No automation.",
            "trigger_type": "manual_only",
            "trigger_config": {"stage_id": "sistema"},
            "definition": {"status": "draft", "nodes": [], "edges": [], "real_send_enabled": False},
        },
    ]


async def scalar(session, sql: str, params: dict[str, Any]) -> Any:
    return (await session.execute(text(sql), params)).scalar_one_or_none()


async def counts_for_tenant(session, tenant_id: UUID) -> dict[str, int]:
    tables = [
        "agents",
        "catalogs",
        "catalog_items",
        "catalog_item_plans",
        "customer_field_definitions",
        "knowledge_sources",
        "knowledge_items",
        "knowledge_os_chunks",
        "onboarding_states",
        "tenant_pipelines",
        "workflows",
        "tenant_tools_config",
        "tenant_branding",
    ]
    result: dict[str, int] = {}
    for table in tables:
        result[table] = int(
            await scalar(session, f"SELECT count(*) FROM {table} WHERE tenant_id=:tenant_id", {"tenant_id": tenant_id})
            or 0
        )
    return result


async def insert_knowledge(session, sources_report: dict[str, dict[str, Any]]) -> dict[str, Any]:
    source_defs = [
        {
            "key": "catalogo_dinamo",
            "name": "catalogo_dinamo",
            "type": "file",
            "content_type": "catalog",
            "priority": 100,
            "file": "catalogo_dinamo.docx",
            "retrieval_enabled": True,
            "enabled_for_agent": True,
        },
        {
            "key": "requisitos_dinamo",
            "name": "requisitos_dinamo",
            "type": "file",
            "content_type": "document_rules",
            "priority": 95,
            "file": "requisitos_dinamo.docx",
            "retrieval_enabled": True,
            "enabled_for_agent": True,
        },
        {
            "key": "faq_dinamo",
            "name": "faq_dinamo",
            "type": "file",
            "content_type": "faq",
            "priority": 80,
            "file": "faq_dinamo.docx",
            "retrieval_enabled": True,
            "enabled_for_agent": True,
        },
        {
            "key": "prompt_agente_dinamo",
            "name": "prompt_agente_dinamo",
            "type": "manual",
            "content_type": "general",
            "priority": 10,
            "file": "prompt_agente_dinamo.txt",
            "retrieval_enabled": False,
            "enabled_for_agent": False,
            "original_content_type": "agent_instructions",
            "use_as_agent_studio_instructions": True,
        },
        {
            "key": "flujo_dinamo_orden_caos",
            "name": "flujo_dinamo_orden_caos",
            "type": "file",
            "content_type": "general",
            "priority": 5,
            "file": "flujo_dinamo_orden_caos.docx",
            "retrieval_enabled": False,
            "enabled_for_agent": False,
            "original_content_type": "eval_scenarios/operating_guide",
            "use_for_eval_lab": True,
            "use_for_simulation_fixtures": True,
        },
    ]
    target_dir = REPO_ROOT / "docs" / "tenant_sources" / "dinamo"
    source_ids: dict[str, UUID] = {}
    chunks = 0
    items = 0
    catalog_data = load_json(REPO_ROOT / "docs" / "CatalogoMotos2026_DINAMO.json")
    requisitos_data = load_json(REPO_ROOT / "docs" / "Requisitos_Credito_Dinamo.json")
    faq_data = load_json(REPO_ROOT / "docs" / "FAQ_DINAMO.json")
    for src in source_defs:
        sid = uid(f"knowledge_source:{src['key']}")
        source_ids[src["key"]] = sid
        metadata = {
            "key": src["key"],
            "file": f"docs/tenant_sources/dinamo/{src['file']}",
            "retrieval_enabled": src["retrieval_enabled"],
            "enabled_for_agent": src["enabled_for_agent"],
            "setup": SETUP_KEY,
            "checksum": sources_report.get(src["file"], {}).get("sha256"),
            **{k: v for k, v in src.items() if k.startswith("original_") or k.startswith("use_")},
        }
        await session.execute(
            text(
                """
                INSERT INTO knowledge_sources
                    (id, tenant_id, name, type, content_type, status, owner, priority, metadata_json)
                VALUES
                    (:id, :tenant_id, :name, :type, :content_type, 'active', :owner, :priority, CAST(:metadata AS jsonb))
                """
            ),
            {
                "id": sid,
                "tenant_id": TENANT_ID,
                "name": src["name"],
                "type": src["type"],
                "content_type": src["content_type"],
                "owner": EMAIL,
                "priority": src["priority"],
                "metadata": dumps(metadata),
            },
        )

    async def add_item(source_key: str, title: str, content: str, structured: Any, metadata: dict[str, Any]) -> None:
        nonlocal chunks, items
        source_id = source_ids[source_key]
        item_id = uid(f"knowledge_item:{source_key}:{title}")
        await session.execute(
            text(
                """
                INSERT INTO knowledge_items
                    (id, tenant_id, source_id, title, content, structured_data, status, active, metadata_json)
                VALUES
                    (:id, :tenant_id, :source_id, :title, :content, CAST(:structured AS jsonb),
                     'active', :active, CAST(:metadata AS jsonb))
                """
            ),
            {
                "id": item_id,
                "tenant_id": TENANT_ID,
                "source_id": source_id,
                "title": title[:300],
                "content": content,
                "structured": dumps(structured),
                "active": bool(metadata.get("retrieval_enabled", True)),
                "metadata": dumps(metadata),
            },
        )
        items += 1
        for index, chunk in enumerate(chunk_text(content)):
            chunks += 1
            await session.execute(
                text(
                    """
                    INSERT INTO knowledge_os_chunks
                        (id, tenant_id, source_id, item_id, chunk_text, chunk_index, status, metadata_json)
                    VALUES
                        (:id, :tenant_id, :source_id, :item_id, :chunk_text, :chunk_index, 'active', CAST(:metadata AS jsonb))
                    """
                ),
                {
                    "id": uid(f"knowledge_chunk:{source_key}:{title}:{index}"),
                    "tenant_id": TENANT_ID,
                    "source_id": source_id,
                    "item_id": item_id,
                    "chunk_text": chunk,
                    "chunk_index": index,
                    "metadata": dumps({"setup": SETUP_KEY, "source_key": source_key}),
                },
            )

    for model in catalog_data.get("modelos", []):
        await add_item(
            "catalogo_dinamo",
            str(model.get("modelo_moto") or model.get("modelo")),
            str(model.get("texto_retrieval") or json.dumps(model, ensure_ascii=False)),
            model,
            {"retrieval_enabled": True, "category": "catalog", "setup": SETUP_KEY},
        )
    for plan in requisitos_data.get("planes", []):
        title = str(plan.get("tipo_credito") or plan.get("plan_id"))
        await add_item(
            "requisitos_dinamo",
            title,
            json.dumps(plan, ensure_ascii=False, indent=2),
            plan,
            {"retrieval_enabled": True, "category": "document_rules", "setup": SETUP_KEY},
        )
    await add_item(
        "requisitos_dinamo",
        "reglas_globales_requisitos",
        json.dumps(requisitos_data.get("reglas_globales", {}), ensure_ascii=False, indent=2),
        requisitos_data.get("reglas_globales", {}),
        {"retrieval_enabled": True, "category": "document_rules", "setup": SETUP_KEY},
    )
    for faq in faq_data.get("faq", []):
        await add_item(
            "faq_dinamo",
            str(faq.get("pregunta") or "FAQ"),
            json.dumps(faq, ensure_ascii=False, indent=2),
            faq,
            {"retrieval_enabled": True, "category": "faq", "setup": SETUP_KEY},
        )
    for source_key, filename in [
        ("prompt_agente_dinamo", "prompt_agente_dinamo.txt"),
        ("flujo_dinamo_orden_caos", "flujo_dinamo_orden_caos.docx"),
    ]:
        path = target_dir / filename
        await add_item(
            source_key,
            source_key,
            source_text(path),
            {"file": f"docs/tenant_sources/dinamo/{filename}"},
            {"retrieval_enabled": False, "category": "non_factual", "setup": SETUP_KEY},
        )
    return {"source_ids": {k: str(v) for k, v in source_ids.items()}, "items": items, "chunks": chunks}


async def insert_commercial_catalog(session, user_id: UUID) -> dict[str, Any]:
    data = load_json(REPO_ROOT / "docs" / "CatalogoMotos2026_DINAMO.json")
    catalog_id = uid("commercial_catalog:catalogo_dinamo")
    version_id = uid("commercial_catalog:catalogo_dinamo:v1")
    await session.execute(
        text(
            """
            INSERT INTO catalogs (id, tenant_id, name, vertical, currency, status)
            VALUES (:id, :tenant_id, 'Catalogo Dinamo 2026', 'motorcycles', 'MXN', 'active')
            """
        ),
        {"id": catalog_id, "tenant_id": TENANT_ID},
    )
    item_count = 0
    plan_count = 0
    for model in data.get("modelos", []):
        item_id = uid(f"catalog_item:{model['id']}")
        item_count += 1
        await session.execute(
            text(
                """
                INSERT INTO catalog_items
                    (id, tenant_id, catalog_id, sku, name, type, category, base_price, list_price,
                     stock_status, status, attributes_json, ai_rules_json, tags_json)
                VALUES
                    (:id, :tenant_id, :catalog_id, :sku, :name, 'motorcycle', :category, :base_price, :list_price,
                     'unknown', 'active', CAST(:attrs AS jsonb), CAST(:rules AS jsonb), CAST(:tags AS jsonb))
                """
            ),
            {
                "id": item_id,
                "tenant_id": TENANT_ID,
                "catalog_id": catalog_id,
                "sku": model["id"],
                "name": model.get("modelo_moto") or model.get("modelo"),
                "category": model.get("categoria"),
                "base_price": model.get("precio_contado_mxn"),
                "list_price": model.get("precio_lista_mxn"),
                "attrs": dumps(model),
                "rules": dumps(
                    {
                        "quote_requires_plan": True,
                        "quote_source": "catalogo_dinamo",
                        "do_not_calculate": True,
                        "do_not_invent_availability": True,
                    }
                ),
                "tags": dumps(model.get("tags_uso") or []),
            },
        )
        for plan_code, plan in (model.get("planes_credito_normalizados") or {}).items():
            plan_count += 1
            await session.execute(
                text(
                    """
                    INSERT INTO catalog_item_plans
                        (id, tenant_id, catalog_item_id, plan_name, plan_code, plan_type,
                         down_payment_amount, down_payment_percent, installment_amount,
                         installment_frequency, installment_count, eligibility_rules_json, status)
                    VALUES
                        (:id, :tenant_id, :catalog_item_id, :plan_name, :plan_code, 'credit',
                         :down_payment_amount, :down_payment_percent, :installment_amount,
                         'biweekly', :installment_count, CAST(:eligibility AS jsonb), 'active')
                    """
                ),
                {
                    "id": uid(f"catalog_plan:{model['id']}:{plan_code}"),
                    "tenant_id": TENANT_ID,
                    "catalog_item_id": item_id,
                    "plan_name": f"Credito {plan_code}",
                    "plan_code": plan_code,
                    "down_payment_amount": plan.get("enganche_mxn"),
                    "down_payment_percent": plan.get("porcentaje_enganche"),
                    "installment_amount": plan.get("pago_quincenal_mxn"),
                    "installment_count": plan.get("numero_quincenas"),
                    "eligibility": dumps({"plan_enganche": plan_code, "source": "catalogo_dinamo"}),
                },
            )
    await session.execute(
        text(
            """
            INSERT INTO catalog_versions
                (id, tenant_id, catalog_id, version_number, status, snapshot_json, created_by, published_at)
            VALUES
                (:id, :tenant_id, :catalog_id, 1, 'published', CAST(:snapshot AS jsonb), :created_by, now())
            """
        ),
            {
                "id": version_id,
                "tenant_id": TENANT_ID,
                "catalog_id": catalog_id,
                "snapshot": dumps({"source": "CatalogoMotos2026_DINAMO.json", "models": data.get("modelos", [])}),
                "created_by": user_id,
            },
    )
    await session.execute(
        text("UPDATE catalogs SET active_version_id=:version_id WHERE id=:catalog_id"),
        {"version_id": version_id, "catalog_id": catalog_id},
    )
    return {"catalog_id": str(catalog_id), "items": item_count, "plans": plan_count}


async def main() -> None:
    sources_report = normalize_sources()
    reports_dir = REPO_ROOT / "docs" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    fixture_dir = CORE_DIR / "atendia" / "simulation" / "fixtures"
    fixture_dir.mkdir(parents=True, exist_ok=True)

    prompt_text = source_text(REPO_ROOT / "docs" / "tenant_sources" / "dinamo" / "prompt_agente_dinamo.txt")
    instructions = mandatory_instructions(prompt_text)
    pipeline = pipeline_definition()
    factory = _get_factory()

    async with factory() as session:
        candidates = (
            await session.execute(
                text(
                    """
                    SELECT tu.id user_id, tu.email, tu.role, tu.tenant_id, t.name, t.config, t.is_demo
                    FROM tenant_users tu
                    JOIN tenants t ON t.id = tu.tenant_id
                    WHERE lower(tu.email)=lower(:email)
                    ORDER BY t.is_demo ASC, t.created_at DESC
                    """
                ),
                {"email": EMAIL},
            )
        ).mappings().all()
        if len(candidates) != 1 or candidates[0]["tenant_id"] != TENANT_ID:
            raise SystemExit(f"Unexpected tenant candidates for {EMAIL}: {candidates}")
        user_id = candidates[0]["user_id"]
        before_counts = await counts_for_tenant(session, TENANT_ID)

        workflow_child_tables = [
            "workflow_dependencies",
            "workflow_variables",
            "workflow_versions",
        ]
        cleanup_tables = [
            "workflows",
            "knowledge_os_chunks",
            "knowledge_items",
            "knowledge_sources",
            "catalog_item_plans",
            "catalog_items",
            "catalog_versions",
            "catalogs",
            "customer_field_definitions",
            "agents",
            "ai_agents",
            "knowledge_base_sources",
            "tenant_tools_config",
            "tenant_branding",
            "tenant_pipelines",
            "onboarding_states",
            "tenant_catalogs",
            "tenant_faqs",
        ]
        deleted: dict[str, int] = {}
        for table_name in workflow_child_tables:
            result = await session.execute(
                text(
                    f"""
                    DELETE FROM {table_name}
                    WHERE workflow_id IN (
                        SELECT id FROM workflows WHERE tenant_id=:tenant_id
                    )
                    """
                ),
                {"tenant_id": TENANT_ID},
            )
            deleted[table_name] = int(result.rowcount or 0)
        for table_name in cleanup_tables:
            result = await session.execute(
                text(f"DELETE FROM {table_name} WHERE tenant_id=:tenant_id"),
                {"tenant_id": TENANT_ID},
            )
            deleted[table_name] = int(result.rowcount or 0)

        knowledge = await insert_knowledge(session, sources_report)
        catalog = await insert_commercial_catalog(session, user_id)

        for field in contact_fields():
            await session.execute(
                text(
                    """
                    INSERT INTO customer_field_definitions
                        (id, tenant_id, key, label, field_type, field_options, ordering)
                    VALUES
                        (:id, :tenant_id, :key, :label, :field_type, CAST(:field_options AS jsonb), :ordering)
                    """
                ),
                {
                    "id": uid(f"field:{field['key']}"),
                    "tenant_id": TENANT_ID,
                    **field,
                    "field_options": dumps(field["field_options"]),
                },
            )

        await session.execute(
            text(
                """
                INSERT INTO tenant_pipelines (id, tenant_id, version, definition, active, history)
                VALUES (:id, :tenant_id, 1, CAST(:definition AS jsonb), true, '[]'::jsonb)
                """
            ),
            {"id": uid("tenant_pipeline:v1"), "tenant_id": TENANT_ID, "definition": dumps(pipeline)},
        )

        enabled_source_ids = [
            knowledge["source_ids"]["catalogo_dinamo"],
            knowledge["source_ids"]["requisitos_dinamo"],
            knowledge["source_ids"]["faq_dinamo"],
        ]
        agent_id = uid("agent:francisco_de_dinamo_nl")
        studio = {
            "template": "sales",
            "instructions": instructions,
            "tone": "WhatsApp directo",
            "language_policy": {"primary": "es-MX", "mode": "force"},
            "enabled_knowledge_source_ids": enabled_source_ids,
            "enabled_action_ids": [
                "update_contact_field",
                "move_lifecycle",
                "assign_conversation",
                "close_conversation",
                "trigger_workflow",
            ],
            "visible_contact_field_keys": FIELD_KEYS,
            "allowed_lifecycle_stage_ids": [
                "nuevos",
                "plan",
                "cliente_potencial",
                "papeleria_incompleta",
                "papeleria_completa",
                "galgo",
                "sistema",
                "cliente_cerrado",
            ],
            "escalation_policy": {
                "handoff_field": "Handoff_Humano",
                "human_request_sets_handoff": True,
                "rare_or_low_confidence_sets_handoff": True,
            },
            "metadata": {"setup": SETUP_KEY, "owner": EMAIL, "live_ready": False},
        }
        await session.execute(
            text(
                """
                INSERT INTO agents
                    (id, tenant_id, name, role, status, behavior_mode, version, goal, style, tone,
                     language, max_sentences, no_emoji, return_to_flow, is_default,
                     system_prompt, active_intents, extraction_config, auto_actions,
                     knowledge_config, flow_mode_rules, ops_config)
                VALUES
                    (:id, :tenant_id, :name, 'sales_agent', 'production', 'strict', :version, :goal, :style, :tone,
                     'es-MX', 2, true, true, true,
                     :system_prompt, CAST(:active_intents AS jsonb), CAST(:extraction_config AS jsonb),
                     CAST(:auto_actions AS jsonb), CAST(:knowledge_config AS jsonb),
                     CAST(:flow_mode_rules AS jsonb), CAST(:ops_config AS jsonb))
                """
            ),
            {
                "id": agent_id,
                "tenant_id": TENANT_ID,
                "name": "Francisco de Dinamo NL",
                "version": "dinamo-fresh-v1",
                "goal": "Calificar leads, cotizar motos con catalogo real y preparar revision humana sin enviar mensajes reales.",
                "style": "WhatsApp directo, maximo 2 frases, sin emojis.",
                "tone": "directo",
                "system_prompt": instructions,
                "active_intents": dumps(["GREETING", "ASK_INFO", "ASK_PRICE", "BUY", "HUMAN_REQUESTED"]),
                "extraction_config": dumps({"visible_contact_field_keys": FIELD_KEYS, "official_fields": FIELD_KEYS}),
                "auto_actions": dumps(
                    {
                        "enabled_action_ids": studio["enabled_action_ids"],
                        "actions_enabled": False,
                        "execution_mode": "preview_only",
                    }
                ),
                "knowledge_config": dumps(
                    {
                        "enabled_source_ids": enabled_source_ids,
                        "disabled_factual_source_keys": ["prompt_agente_dinamo", "flujo_dinamo_orden_caos"],
                    }
                ),
                "flow_mode_rules": dumps({"allowed_stage_ids": studio["allowed_lifecycle_stage_ids"]}),
                "ops_config": dumps({"agent_studio_v2": studio, "guardrails": [], "versions": []}),
            },
        )

        await session.execute(
            text(
                """
                INSERT INTO tenant_branding (tenant_id, bot_name, voice, default_messages)
                VALUES (:tenant_id, 'Francisco', CAST(:voice AS jsonb), CAST(:messages AS jsonb))
                """
            ),
            {
                "tenant_id": TENANT_ID,
                "voice": dumps({"register": "whatsapp_directo", "language": "es-MX", "no_emoji": True, "max_sentences": 2}),
                "messages": dumps(
                    {
                        "documents_complete_handoff": "Listo, recibi tu papeleria completa. La paso a revision y en 24 horas habiles te damos respuesta.",
                        "galgo_close": "Por ahora para credito necesitamos minimo 6 meses de antiguedad. Si mas adelante cumples ese tiempo, con gusto lo revisamos.",
                    }
                ),
            },
        )

        for workflow in workflow_rows():
            await session.execute(
                text(
                    """
                    INSERT INTO workflows
                        (id, tenant_id, name, description, trigger_type, trigger_config, definition, active, version)
                    VALUES
                        (:id, :tenant_id, :name, :description, :trigger_type, CAST(:trigger_config AS jsonb),
                         CAST(:definition AS jsonb), false, 1)
                    """
                ),
                {
                    "tenant_id": TENANT_ID,
                    **{k: v for k, v in workflow.items() if k not in {"trigger_config", "definition"}},
                    "trigger_config": dumps(workflow["trigger_config"]),
                    "definition": dumps(workflow["definition"]),
                },
            )

        for tool_name, config in {
            "QuoteResolver": {
                "execution_mode": "preview_only",
                "catalog_id": catalog["catalog_id"],
                "requires": ["Moto", "Plan_Credito", "Plan_Enganche"],
                "plan_to_enganche": PLAN_TO_ENGANCHE,
                "block_placeholders": True,
            },
            "DocumentChecklistService": {
                "execution_mode": "preview_only",
                "document_requirements_field": "Plan_Credito",
                "document_requirements": DOCUMENT_RULES,
                "accepted_status_required": True,
            },
        }.items():
            await session.execute(
                text(
                    """
                    INSERT INTO tenant_tools_config (id, tenant_id, tool_name, enabled, config)
                    VALUES (:id, :tenant_id, :tool_name, true, CAST(:config AS jsonb))
                    """
                ),
                {"id": uid(f"tool:{tool_name}"), "tenant_id": TENANT_ID, "tool_name": tool_name, "config": dumps(config)},
            )

        tenant_config = {
            "agent_runtime_v2": {
                "runtime_v2_enabled": True,
                "preview_enabled": True,
                "shadow_mode_enabled": False,
                "send_enabled": False,
                "manual_send_enabled": False,
                "auto_send_enabled": False,
                "actions_enabled": False,
                "workflow_events_enabled": False,
                "outbox_enabled": False,
                "model_provider_enabled": True,
                "rollout_mode": "preview_only",
                "required_eval_suite_passed": False,
                "min_eval_score": 0.90,
                "max_actions_per_turn": 2,
                "metadata": {"owner": EMAIL, "setup": SETUP_KEY, "live_ready": False},
            },
            "dinamo_fresh_tenant_v1": {
                "source_checksums": sources_report,
                "document_rules": DOCUMENT_RULES,
                "plan_to_enganche": PLAN_TO_ENGANCHE,
                "ui_sections": {
                    "Datos Comerciales": FIELD_KEYS[:7],
                    "Tecnicos": FIELD_KEYS[7:],
                },
                "manual_stage_ids": ["sistema", "cliente_cerrado"],
                "disabled_real_side_effects": True,
            },
        }
        await session.execute(
            text("UPDATE tenants SET config=CAST(:config AS jsonb), status='active', is_demo=false WHERE id=:tenant_id"),
            {"tenant_id": TENANT_ID, "config": dumps(tenant_config)},
        )

        await session.execute(
            text(
                """
                INSERT INTO onboarding_states
                    (tenant_id, selected_blueprint_id, channel_connected, knowledge_uploaded,
                     agent_configured, contact_fields_ready, lifecycle_ready, test_passed, published,
                     current_step, checklist)
                VALUES
                    (:tenant_id, 'dinamo_fresh_tenant_v1', false, true, true, true, true, false, false,
                     'test_preview', CAST(:checklist AS jsonb))
                """
            ),
            {
                "tenant_id": TENANT_ID,
                "checklist": dumps(
                    {
                        "no_whatsapp": True,
                        "knowledge_os_ready": True,
                        "agent_studio_ready": True,
                        "pipeline_ready": True,
                        "workflows_draft_disabled": True,
                        "tests_pending": True,
                    }
                ),
            },
        )

        after_counts = await counts_for_tenant(session, TENANT_ID)
        await session.commit()

    fixture_path = fixture_dir / "dinamo_fresh_tenant_v1.yaml"
    fixture_path.write_text(simulation_fixture(), encoding="utf-8")

    audit_path = reports_dir / f"dinamo_fresh_tenant_setup_audit_{TODAY}.md"
    final_path = reports_dir / f"dinamo_fresh_tenant_preparation_final_{TODAY}.md"
    simulation_path = reports_dir / f"dinamo_fresh_tenant_simulation_{TODAY}.md"
    audit_path.write_text(
        build_audit_report(candidates, before_counts, deleted, sources_report, str(agent_id), knowledge, catalog),
        encoding="utf-8",
    )
    simulation_path.write_text(build_simulation_report(str(fixture_path.relative_to(REPO_ROOT))), encoding="utf-8")
    final_path.write_text(
        build_final_report(str(agent_id), knowledge, catalog, after_counts, sources_report),
        encoding="utf-8",
    )

    print(json.dumps({
        "tenant_id": str(TENANT_ID),
        "agent_id": str(agent_id),
        "knowledge": knowledge,
        "catalog": catalog,
        "reports": [str(audit_path), str(simulation_path), str(final_path)],
        "fixture": str(fixture_path),
        "after_counts": after_counts,
    }, ensure_ascii=False, indent=2))


def build_audit_report(
    candidates: list[Any],
    before_counts: dict[str, int],
    deleted: dict[str, int],
    sources_report: dict[str, dict[str, Any]],
    agent_id: str,
    knowledge: dict[str, Any],
    catalog: dict[str, Any],
) -> str:
    candidate_lines = "\n".join(
        f"- user_id={row['user_id']} email={row['email']} role={row['role']} tenant_id={row['tenant_id']} name={row['name']} is_demo={row['is_demo']}"
        for row in candidates
    )
    source_lines = "\n".join(f"- {name}: sha256={meta['sha256']} bytes={meta['bytes']}" for name, meta in sources_report.items())
    before_lines = "\n".join(f"- {k}: {v}" for k, v in before_counts.items())
    deleted_lines = "\n".join(f"- {k}: {v}" for k, v in deleted.items() if v)
    return f"""# Dinamo Fresh Tenant Setup Audit - 2026-06-02

## Tenant detection
Email: {EMAIL}
Selected tenant_id: {TENANT_ID}
Selected agent_id: {agent_id}

## Candidates
{candidate_lines}

## Initial tenant-scoped counts
{before_lines}

## Cleanup applied
{deleted_lines or "- No prior setup rows found."}

## Sources normalized
{source_lines}

## Will create / created
- Knowledge sources: {len(knowledge['source_ids'])}
- Knowledge items: {knowledge['items']}
- Knowledge chunks: {knowledge['chunks']}
- Commercial catalog items: {catalog['items']}
- Commercial catalog plans: {catalog['plans']}
- Contact fields: {len(FIELD_KEYS)}
- Pipeline stages: 8
- Workflows: 4 draft/disabled

## Warnings
- The tenant uses the real existing tenant_id by explicit instruction.
- KnowledgeSource content_type does not support agent_instructions or eval_scenarios; prompt and flow are stored as general with original_content_type metadata.
- Ultima_Cotizacion and Docs_Checklist are stored as text fields with render_mode metadata because the field schema does not provide a native json field_type.
- Provider battery and realistic simulation are pending; rollout remains preview_only.
"""


def build_final_report(
    agent_id: str,
    knowledge: dict[str, Any],
    catalog: dict[str, Any],
    after_counts: dict[str, int],
    sources_report: dict[str, dict[str, Any]],
) -> str:
    fields = "\n".join(f"| {f} | configured | visible | editable per policy | ok |" for f in FIELD_KEYS)
    docs = "\n".join(
        f"| {plan} | {PLAN_TO_ENGANCHE[plan]} | {', '.join(docs) if docs else 'none'} |"
        for plan, docs in DOCUMENT_RULES.items()
    )
    source_rows = "\n".join(
        f"| {key} | configured | {key in ['catalogo_dinamo', 'requisitos_dinamo', 'faq_dinamo']} | {key in ['catalogo_dinamo', 'requisitos_dinamo', 'faq_dinamo']} | active |"
        for key in knowledge["source_ids"]
    )
    checksum_lines = "\n".join(f"- {name}: {meta['sha256']}" for name, meta in sources_report.items())
    return f"""# Dinamo Fresh Tenant Preparation Final - 2026-06-02

## Executive summary
- email: {EMAIL}
- tenant_id: {TENANT_ID}
- agent_id: {agent_id}
- rollout_mode: preview_only
- ready_for_preview: true
- ready_for_shadow: false
- ready_for_manual_send: false

## Knowledge sources
| key | content_type | retrieval_enabled | enabled_for_agent | status |
| --- | --- | --- | --- | --- |
{source_rows}

## Contact fields
| key | type | visible | editable | status |
| --- | --- | --- | --- | --- |
{fields}

## Technical visible fields
| key | render mode | status |
| --- | --- | --- |
| Cotizacion_Enviada | checkbox | ok |
| Ultima_Cotizacion | quote_card | ok |
| Docs_Checklist | document_checklist | ok |
| Handoff_Humano | checkbox | ok |

## Pipeline
| stage | key | automatic/manual |
| --- | --- | --- |
| Nuevos | nuevos | automatic |
| Plan | plan | automatic |
| Cliente Potencial | cliente_potencial | automatic |
| Papeleria Incompleta | papeleria_incompleta | automatic |
| Papeleria Completa | papeleria_completa | automatic |
| Galgo | galgo | automatic |
| Sistema | sistema | manual |
| Cliente Cerrado | cliente_cerrado | manual |

## Document rules
| Plan_Credito | Plan_Enganche | required docs |
| --- | --- | --- |
{docs}

## Workflows
| workflow | trigger | status | real_send_enabled |
| --- | --- | --- | --- |
| workflow_doc_completos_handoff | Doc_Completos=true | draft/disabled | false |
| workflow_galgo_close | Cumple_Antiguedad=false | draft/disabled | false |
| workflow_cliente_cerrado_manual | manual only | draft/disabled | false |
| workflow_sistema_manual | manual only | draft/disabled | false |

## Agent Studio
- name: Francisco de Dinamo NL
- role: sales_agent
- enabled sources: catalogo_dinamo, requisitos_dinamo, faq_dinamo
- disabled factual sources: prompt_agente_dinamo, flujo_dinamo_orden_caos
- allowed actions exist only for preview/simulation; tenant actions_enabled=false.

## Simulation results
- provider battery score: not run
- realistic simulation score: not run
- fixture: core/atendia/simulation/fixtures/dinamo_fresh_tenant_v1.yaml
- failures: pending execution
- side effects: 0 expected by configuration

## UI readiness
- Fields are clean and official only.
- JSON-like technical fields carry render_mode metadata.
- Requirement rules live in tenant config and pipeline definition; frontend editing surface exists for fields/pipeline/workflows, but plan-rule UI may need product polish.

## Safety
- WhatsApp sends: 0
- outbox writes: 0
- real customer writes during setup: 0
- real lifecycle moves during setup: 0
- real actions: 0
- workflow executions: 0

## Counts
```json
{json.dumps(after_counts, ensure_ascii=False, indent=2)}
```

## Checksums
{checksum_lines}

## Next steps
1. Run 10 live previews no-send.
2. Run OpenAI shadow after provider battery passes.
3. Enable manual-send limited only after review.
4. Do not enable auto-send yet.

## Gaps
- Provider battery and full simulation were not executed by this setup script.
- Native field_type=json is unavailable, so rendered JSON fields use text + metadata.
- KnowledgeSource content_type is constrained; non-factual prompt/flow sources use general + metadata.
"""


def build_simulation_report(fixture: str) -> str:
    return f"""# Dinamo Fresh Tenant Simulation - 2026-06-02

Fixture created: {fixture}

Status: pending execution.

Expected gate criteria:
- 10/10 conversations pass.
- Quote placeholders = 0.
- Real quote coverage = 100% when Moto + Plan_Credito exist.
- Papeleria Incompleta only after document attachment.
- Doc_Completos only with all required documents accepted.
- Autorizado is not written by AI.
- Sistema and Cliente Cerrado are not moved by AI.
- flujo_dinamo_orden_caos is never used as factual customer source.
- Real side effects = 0.
"""


def simulation_fixture() -> str:
    return """name: dinamo_fresh_tenant_v1
tenant: Dinamo Motos NL
tenant_id: 6ad78236-1fc9-467a-858d-90d248d57ee5
runtime: agent_runtime_v2
rollout_mode: preview_only
global_hard_fails:
  - quote_placeholders
  - papeleria_incompleta_without_attachment
  - doc_completos_without_accepted_checklist
  - quote_without_quote_resolver
  - autorizado_written_by_ai
  - automatic_move_to_sistema_or_cliente_cerrado
  - flujo_used_as_factual_source
cases:
  - case_id: credito_happy_path_nomina_tarjeta
    turns:
      - customer: Hola, quiero una moto a credito.
      - customer: Tengo 8 meses trabajando.
      - customer: Me interesa la Comando.
      - customer: Me depositan en tarjeta.
      - customer: Si me dan recibos.
      - customer: Mi comprobante puede estar a otro nombre?
      - customer: Que documentos siguen?
      - customer: Mando mi INE.
        attachment: ine_ambos_lados.jpg
      - customer: Mando estado de cuenta, nomina y comprobante.
        attachments: [estado_cuenta.pdf, nomina.pdf, comprobante.jpg]
    expected:
      Cumple_Antiguedad: true
      Plan_Credito: Nomina Tarjeta
      Plan_Enganche: 10%
      Cotizacion_Enviada: true
      stage_after_quote: cliente_potencial
      stage_after_first_attachment: papeleria_incompleta
      Doc_Completos: true
      Handoff_Humano: true
  - case_id: no_cumple_antiguedad
    turns:
      - customer: Quiero credito.
      - customer: Tengo 2 meses trabajando.
    expected:
      Cumple_Antiguedad: false
      stage: galgo
      no_plan: true
      no_docs: true
  - case_id: contado_directo
    turns:
      - customer: Quiero comprar de contado la R4.
    expected:
      Plan_Credito: Contado
      Plan_Enganche: 100%
      Cotizacion_Enviada: true
      stage: cliente_potencial
      no_credit_docs: true
  - case_id: sin_comprobantes
    turns:
      - customer: Tengo 1 ano trabajando.
      - customer: Me pagan por fuera.
      - customer: Quiero una U5.
    expected:
      Plan_Credito: Sin Comprobantes
      Plan_Enganche: 20%
      required_docs: [INE_AMBOS_LADOS, COMPROBANTE_DOMICILIO]
  - case_id: nomina_recibos
    turns:
      - customer: Tengo 10 meses.
      - customer: Me pagan efectivo pero tengo recibos.
    expected:
      Plan_Credito: Nomina Recibos
      Plan_Enganche: 15%
  - case_id: guardia
    turns:
      - customer: Tengo 2 anos trabajando.
      - customer: Soy guardia de seguridad.
    expected:
      Plan_Credito: Guardia
      Plan_Enganche: 30%
  - case_id: documentos_mama
    turns:
      - customer: Puedo mandar documentos de mi mama?
    expected:
      answer_mentions: [comprobante domicilio puede ser familiar, ingresos deben ser del cliente]
      no_stage: papeleria_incompleta
  - case_id: documento_antes_de_plan
    turns:
      - customer: Te mando mi INE.
        attachment: ine.jpg
      - customer: Que sigue?
    expected:
      Doc_Completos: false
      no_stage: papeleria_completa
      asks_missing_data: true
  - case_id: modelo_ambiguo
    turns:
      - customer: Quiero la R4.
    expected:
      resolve_exact_if_catalog_allows: true
      max_options_if_ambiguous: 3
      no_invention: true
  - case_id: cliente_pide_humano
    turns:
      - customer: Quiero hablar con alguien.
    expected:
      Handoff_Humano: true
      needs_human: true
      no_stage_handoff: true
"""


if __name__ == "__main__":
    asyncio.run(main())
