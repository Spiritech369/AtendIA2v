"""Seed a full mock workspace for functional testing.

Run from ``core/``:

    uv run python scripts/seed_full_mock_data.py

The seed targets the ``demo`` tenant, creates login-ready demo users and
refreshes mock rows tagged/prefixed with ``mock-full``. It intentionally covers
all operator-facing features with enough volume to exercise filters, counters,
lists, detail pages and command centers.
"""

# ruff: noqa: E501, PLR0912, PLR0915
from __future__ import annotations

import asyncio
import json
import random
import sys
from collections import Counter
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Text as SAText
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import ARRAY as PG_ARRAY
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from atendia.api._auth_helpers import hash_password
from atendia.config import get_settings

DEMO_TENANT_NAME = "demo"
DEMO_PASSWORD = "admin123"
MOCK_SEED = "full_mock_v1"
MOCK_TAG = "mock-full"
NOW = datetime.now(UTC)


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def dt(hours: int = 0, minutes: int = 0, days: int = 0) -> datetime:
    return NOW + timedelta(days=days, hours=hours, minutes=minutes)


def stage_label(stage: str) -> str:
    return stage.replace("_", " ").title()


def money(amount: int) -> str:
    return f"${amount:,.0f} MXN"


PIPELINE_DEFINITION = {
    "version": "mock-full-20260511",
    "stages": [
        {
            "id": "nuevo_lead",
            "label": "Nuevo lead",
            "timeout_hours": 2,
            "color": "#0ea5e9",
            "icon": "inbox",
            "allowed_transitions": ["calificacion", "cierre_perdido"],
        },
        {
            "id": "calificacion",
            "label": "Calificacion",
            "timeout_hours": 4,
            "color": "#22c55e",
            "icon": "list_checks",
            "allowed_transitions": ["documentacion", "propuesta", "cierre_perdido"],
        },
        {
            "id": "documentacion",
            "label": "Documentacion",
            "timeout_hours": 12,
            "color": "#8b5cf6",
            "icon": "file_text",
            "allowed_transitions": ["validacion", "calificacion"],
        },
        {
            "id": "validacion",
            "label": "Validacion",
            "timeout_hours": 18,
            "color": "#f59e0b",
            "icon": "clipboard_check",
            "allowed_transitions": ["propuesta", "documentacion"],
        },
        {
            "id": "propuesta",
            "label": "Propuesta",
            "timeout_hours": 24,
            "color": "#6366f1",
            "icon": "send",
            "allowed_transitions": ["negociacion", "cita_agendada", "cierre_perdido"],
        },
        {
            "id": "negociacion",
            "label": "Negociacion",
            "timeout_hours": 24,
            "color": "#a855f7",
            "icon": "handshake",
            "allowed_transitions": ["cita_agendada", "cierre_ganado", "cierre_perdido"],
        },
        {
            "id": "cita_agendada",
            "label": "Cita agendada",
            "timeout_hours": 10,
            "color": "#06b6d4",
            "icon": "calendar",
            "allowed_transitions": ["cierre_ganado", "cierre_perdido", "negociacion"],
        },
        {
            "id": "cierre_ganado",
            "label": "Cierre ganado",
            "timeout_hours": 72,
            "color": "#10b981",
            "icon": "check_circle",
            "is_terminal": True,
        },
        {
            "id": "cierre_perdido",
            "label": "Cierre perdido",
            "timeout_hours": 72,
            "color": "#ef4444",
            "icon": "x_circle",
            "is_terminal": True,
        },
    ],
    "flow_mode_rules": {
        "PLAN": ["nuevo_lead", "calificacion"],
        "SALES": ["propuesta", "negociacion", "cita_agendada"],
        "DOC": ["documentacion", "validacion"],
        "RETENTION": ["cierre_perdido"],
        "SUPPORT": ["postventa", "soporte"],
    },
    "docs_per_plan": {
        "Plan 10%": ["INE", "Comprobante de domicilio", "Recibo de nomina"],
        "48 meses + 15% enganche": ["INE", "Comprobante de domicilio", "Estados de cuenta"],
        "Contado": ["INE", "Comprobante de domicilio"],
    },
    "brand_facts": [
        "AtendIA Demo Motors opera como distribuidor mock para pruebas funcionales.",
        "No confirmar aprobaciones, tasas, precios finales o inventario sin fuente publicada.",
        "Toda cita de prueba de manejo requiere confirmacion de asesor.",
    ],
}

STAGE_RING_EMOJI = {
    "nuevo_lead": "N",
    "calificacion": "Q",
    "documentacion": "D",
    "validacion": "V",
    "propuesta": "$",
    "negociacion": "%",
    "cita_agendada": "@",
    "cierre_ganado": "+",
    "cierre_perdido": "!",
}

INBOX_CONFIG = {
    "mock_seed": MOCK_SEED,
    "layout": {
        "three_pane": True,
        "rail_width": "expanded",
        "list_max_width": 360,
        "composer_density": "comfortable",
        "sticky_composer": True,
    },
    "filter_chips": [
        {
            "id": "unread",
            "label": "Sin leer",
            "color": "#4f72f5",
            "query": "read_at IS NULL",
            "live_count": True,
            "visible": True,
            "order": 0,
        },
        {
            "id": "mine",
            "label": "Mias",
            "color": "#9b72f5",
            "query": "assigned_to = current_user",
            "live_count": True,
            "visible": True,
            "order": 1,
        },
        {
            "id": "unassigned",
            "label": "Sin asignar",
            "color": "#f5a623",
            "query": "assigned_to IS NULL AND status != 'closed'",
            "live_count": False,
            "visible": True,
            "order": 2,
        },
        {
            "id": "risk",
            "label": "Riesgo alto",
            "color": "#f25252",
            "query": "risk_level IN ('high','critical')",
            "live_count": True,
            "visible": True,
            "order": 3,
        },
        {
            "id": "sla",
            "label": "SLA vencido",
            "color": "#f59e0b",
            "query": "sla_status = 'breached'",
            "live_count": True,
            "visible": True,
            "order": 4,
        },
    ],
    "stage_rings": [
        {
            "stage_id": stage["id"],
            "emoji": STAGE_RING_EMOJI.get(stage["id"], "o"),
            "color": stage.get("color", "#6b7280"),
            "sla_hours": stage.get("timeout_hours"),
        }
        for stage in PIPELINE_DEFINITION["stages"]
    ],
    "handoff_rules": [
        {
            "id": "human_req",
            "intent": "HUMAN_REQUESTED",
            "confidence": 90,
            "action": "assign_to_free_operator",
            "template": "",
            "enabled": True,
            "order": 0,
        },
        {
            "id": "credit_docs",
            "intent": "CREDIT_APPLICATION",
            "confidence": 82,
            "action": "send_checklist",
            "template": "mock_docs_faltantes",
            "enabled": True,
            "order": 1,
        },
        {
            "id": "ask_price",
            "intent": "ASK_PRICE",
            "confidence": 78,
            "action": "suggest_template",
            "template": "mock_cotizacion",
            "enabled": True,
            "order": 2,
        },
        {
            "id": "stale_sla",
            "intent": "STALE_SLA",
            "confidence": 100,
            "action": "trigger_followup",
            "template": "mock_reactivacion",
            "enabled": False,
            "order": 3,
        },
    ],
}

USERS = [
    ("admin@demo.com", "tenant_admin", "Admin Demo"),
    ("superadmin@demo.com", "superadmin", "Super Admin Demo"),
    ("ana.garcia@demo.com", "operator", "Ana Garcia"),
    ("luis.ramirez@demo.com", "operator", "Luis Ramirez"),
    ("carlos.vega@demo.com", "operator", "Carlos Vega"),
    ("paola.soto@demo.com", "supervisor", "Paola Soto"),
    ("marta.nunez@demo.com", "ai_reviewer", "Marta Nunez"),
    ("diego.rios@demo.com", "sales_agent", "Diego Rios"),
]

ADVISOR_EMAILS = [
    "ana.garcia@demo.com",
    "luis.ramirez@demo.com",
    "carlos.vega@demo.com",
    "diego.rios@demo.com",
]

FIELD_DEFINITIONS = [
    ("modelo_interes", "Modelo de interes", "text", None),
    ("presupuesto", "Presupuesto", "number", None),
    (
        "plan_credito",
        "Plan de credito",
        "select",
        {"choices": ["Plan 10%", "48 meses + 15% enganche", "Contado", "Leasing pyme"]},
    ),
    (
        "tipo_credito",
        "Tipo de credito",
        "select",
        {"choices": ["Bancario", "Nomina", "Contado", "Pyme"]},
    ),
    ("ingreso_mensual", "Ingreso mensual", "number", None),
    ("antiguedad_laboral", "Antiguedad laboral", "text", None),
    ("ciudad", "Ciudad", "text", None),
    (
        "preferencia_contacto",
        "Preferencia de contacto",
        "select",
        {"choices": ["WhatsApp", "Llamada", "Email"]},
    ),
    (
        "objecion_principal",
        "Objecion principal",
        "select",
        {"choices": ["Precio", "Enganche", "Tiempo", "Inventario", "Credito"]},
    ),
    ("fecha_cita_objetivo", "Fecha objetivo de cita", "date", None),
    ("docs_ine", "INE", "checkbox", None),
    ("docs_comprobante", "Comprobante de domicilio", "checkbox", None),
    ("docs_nomina", "Recibos de nomina", "checkbox", None),
    ("docs_estados_cuenta", "Estados de cuenta", "checkbox", None),
]

MODELS = [
    ("HRV-EXL-2026", "HR-V EXL 2026", 524900, "SUV", "Plata Lunar", "in_stock"),
    ("CIVIC-TOURING-2026", "Civic Touring 2026", 649900, "Sedan", "Blanco Platino", "limited"),
    ("CRV-TURBO-2026", "CR-V Turbo 2026", 789900, "SUV", "Gris Meteoro", "in_stock"),
    ("CITY-SPORT-2026", "City Sport 2026", 398900, "Sedan", "Rojo Rally", "in_stock"),
    ("ACCORD-HYBRID-2026", "Accord Hybrid 2026", 918900, "Sedan", "Negro Cristal", "preorder"),
    ("ODYSSEY-TOURING-2026", "Odyssey Touring 2026", 1129900, "Van", "Azul Obsidiana", "limited"),
    ("BRV-PRIME-2026", "BR-V Prime 2026", 469900, "SUV", "Acero", "in_stock"),
    ("PILOT-ELITE-2026", "Pilot Elite 2026", 1249900, "SUV", "Blanco", "preorder"),
]

PLANS = ["Plan 10%", "48 meses + 15% enganche", "Contado", "Leasing pyme"]
SOURCES = [
    "Meta Ads",
    "Google Search",
    "WhatsApp Click",
    "Referido",
    "Landing Page",
    "Expo Auto",
    "Marketplace",
]
CITIES = [
    "CDMX",
    "Guadalajara",
    "Monterrey",
    "Puebla",
    "Queretaro",
    "Toluca",
    "Leon",
    "Merida",
    "Tijuana",
    "Cancun",
]
STAGES = [
    "nuevo_lead",
    "calificacion",
    "documentacion",
    "validacion",
    "propuesta",
    "negociacion",
    "cita_agendada",
    "cierre_ganado",
    "cierre_perdido",
]
CONV_STATUSES = ["active", "active", "active", "paused", "closed"]
RISK_LEVELS = ["low", "medium", "high", "critical"]
SLA_STATUSES = ["on_track", "at_risk", "breached"]
DOC_STATUSES = ["missing", "partial", "complete", "rejected"]
INTENTS = [
    "ASK_INFO",
    "ASK_PRICE",
    "SCHEDULE",
    "CREDIT_APPLICATION",
    "HUMAN_REQUESTED",
    "SERVICE_REQUEST",
    "POSTSALE",
]
FIRST_NAMES = [
    "Diego",
    "Karla",
    "Mariana",
    "Jose",
    "Sofia",
    "Roberto",
    "Valeria",
    "Miguel",
    "Fernanda",
    "Adrian",
    "Patricia",
    "Andres",
    "Camila",
    "Hector",
    "Gabriela",
    "Ricardo",
    "Natalia",
    "Emilio",
    "Monica",
    "Jorge",
    "Daniela",
    "Ivan",
    "Lucia",
    "Rafael",
    "Paola",
    "Santiago",
    "Claudia",
    "Tomas",
    "Beatriz",
    "Oscar",
    "Regina",
    "Arturo",
    "Elena",
    "Samuel",
    "Isabel",
    "Bruno",
    "Renata",
    "Mario",
    "Alicia",
    "Nicolas",
    "Teresa",
    "Victor",
]
LAST_NAMES = [
    "Lopez",
    "Mendez",
    "Perez",
    "Hernandez",
    "Aguilar",
    "Salas",
    "Rojas",
    "Vega",
    "Cano",
    "Torres",
    "Nava",
    "Ruiz",
    "Flores",
    "Castro",
    "Ortega",
    "Santos",
    "Mora",
    "Serrano",
    "Navarro",
    "Campos",
    "Pineda",
    "Mejia",
    "Cortes",
    "Luna",
]

AGENT_SPECS = [
    (
        "[Mock] Recepcionista IA",
        "reception",
        "Capturar intencion inicial, datos minimos y enrutar al flujo correcto.",
        ["GREETING", "ASK_INFO", "SCHEDULE", "HUMAN_REQUESTED"],
    ),
    (
        "[Mock] Sales Agent",
        "sales",
        "Calificar lead, explicar modelos, precios publicados y planes permitidos.",
        ["ASK_PRICE", "BUY", "CREDIT_APPLICATION", "SCHEDULE"],
    ),
    (
        "[Mock] Duda General",
        "duda_general",
        "Responder preguntas frecuentes solo con fuentes publicadas de KB.",
        ["ASK_INFO", "OFF_TOPIC", "UNCLEAR"],
    ),
    (
        "[Mock] Documentacion",
        "documentation",
        "Solicitar y validar documentos por plan de credito.",
        ["CREDIT_APPLICATION", "UNCLEAR", "HUMAN_REQUESTED"],
    ),
    (
        "[Mock] Postventa",
        "postventa",
        "Agendar servicio, garantias y dudas posteriores a venta.",
        ["SERVICE_REQUEST", "POSTSALE", "COMPLAIN"],
    ),
    (
        "[Mock] Supervisor IA",
        "custom",
        "Monitorear riesgos, low confidence y derivaciones humanas.",
        ["HUMAN_REQUESTED", "COMPLAIN", "UNCLEAR"],
    ),
]


def build_agent_ops(name: str, role: str, idx: int) -> dict[str, Any]:
    return {
        "mock_seed": MOCK_SEED,
        "health": {
            "score": 95 - idx * 4,
            "status": "healthy" if idx < 3 else "warning",
            "reasons": [
                "Cobertura mock suficiente",
                "Guardrails activos",
                "Escalacion humana disponible",
            ],
            "suggested_actions": [
                "Revisar escenarios fallidos",
                "Publicar cambios despues de validacion",
            ],
        },
        "metrics": {
            "active_conversations": 18 + idx * 7,
            "response_accuracy": 94 - idx,
            "correct_handoff_rate": 90 - idx,
            "extraction_accuracy": 92 - idx,
            "lead_advancement_rate": 31 + idx,
            "guardrail_compliance": 97 - idx,
            "blocked_responses": idx + 2,
            "stuck_conversations": idx,
            "documents_completed": 24 + idx * 5,
            "appointments_generated": 10 + idx * 3,
            "trend": [82 + ((idx + step) % 12) for step in range(7)],
        },
        "guardrails": [
            {
                "id": "mock_no_approval",
                "severity": "critical",
                "name": "No prometer aprobacion",
                "rule_text": "No confirmar aprobaciones, tasas ni montos sin validacion humana.",
                "allowed_examples": ["Lo validamos con el asesor."],
                "forbidden_examples": ["Ya estas aprobado."],
                "active": True,
                "violation_count": idx + 1,
                "enforcement_mode": "block",
                "updated_by": "Mock seed",
                "updated_at": NOW.isoformat(),
            },
            {
                "id": "mock_no_invented_stock",
                "severity": "high",
                "name": "No inventar inventario",
                "rule_text": "Usar solo catalogo publicado o escalar.",
                "allowed_examples": ["Tengo esta disponibilidad publicada."],
                "forbidden_examples": ["Seguro hay cualquier color."],
                "active": True,
                "violation_count": idx,
                "enforcement_mode": "rewrite",
                "updated_by": "Mock seed",
                "updated_at": NOW.isoformat(),
            },
            {
                "id": "mock_handoff",
                "severity": "medium",
                "name": "Escalar si pide humano",
                "rule_text": "Crear handoff inmediato ante solicitud explicita.",
                "allowed_examples": ["Te conecto con un asesor."],
                "forbidden_examples": ["No necesitas hablar con nadie."],
                "active": True,
                "violation_count": 0,
                "enforcement_mode": "handoff",
                "updated_by": "Mock seed",
                "updated_at": NOW.isoformat(),
            },
        ],
        "extraction_fields": [
            {
                "id": "field_modelo_interes",
                "field_key": "modelo_interes",
                "label": "Modelo de interes",
                "type": "text",
                "required": True,
                "confidence_threshold": 0.88,
                "auto_save": True,
                "requires_confirmation": False,
                "source_message_tracking": True,
                "confidence": 0.93,
                "source": "mock",
                "last_value": MODELS[idx % len(MODELS)][1],
                "status": "confirmed",
            },
            {
                "id": "field_plan_credito",
                "field_key": "plan_credito",
                "label": "Plan de credito",
                "type": "enum",
                "required": True,
                "confidence_threshold": 0.9,
                "auto_save": True,
                "requires_confirmation": True,
                "source_message_tracking": True,
                "enum_options": PLANS,
                "confidence": 0.91,
                "source": "mock",
                "last_value": PLANS[idx % len(PLANS)],
                "status": "pending",
            },
            {
                "id": "field_fecha_cita",
                "field_key": "fecha_cita_objetivo",
                "label": "Fecha objetivo de cita",
                "type": "date",
                "required": False,
                "confidence_threshold": 0.84,
                "auto_save": True,
                "requires_confirmation": True,
                "source_message_tracking": True,
                "confidence": 0.86,
                "source": "mock",
                "last_value": dt(days=idx + 1).date().isoformat(),
                "status": "pending",
            },
        ],
        "live_monitor": {
            "status": "online",
            "last_heartbeat_at": NOW.isoformat(),
            "queue_depth": idx * 3,
            "current_sessions": 8 + idx * 2,
            "low_confidence_events_1h": idx,
        },
        "supervisor": {
            "enabled": True,
            "review_threshold": 0.72,
            "pending_reviews": idx + 3,
            "last_reviewed_at": dt(minutes=-(idx + 2) * 11).isoformat(),
        },
        "knowledge_coverage": {
            "collections": ["credito", "catalogo", "inventario", "postventa"],
            "coverage_percent": 88 - idx * 3,
            "blocked_sources": idx,
            "conflicts": 1 if idx % 2 else 0,
        },
        "decision_map": {
            "nodes": [
                {
                    "id": "incoming",
                    "label": "Incoming",
                    "type": "agent_step",
                    "position": {"x": 40, "y": 120},
                    "enabled": True,
                    "config": {},
                },
                {
                    "id": "intent",
                    "label": "Intent detection",
                    "type": "agent_step",
                    "position": {"x": 230, "y": 120},
                    "enabled": True,
                    "config": {},
                },
                {
                    "id": "kb",
                    "label": "KB retrieval",
                    "type": "agent_step",
                    "position": {"x": 420, "y": 80},
                    "enabled": True,
                    "config": {},
                },
                {
                    "id": "compose",
                    "label": "Composer",
                    "type": "agent_step",
                    "position": {"x": 620, "y": 120},
                    "enabled": True,
                    "config": {},
                },
                {
                    "id": "handoff",
                    "label": "Handoff",
                    "type": "agent_step",
                    "position": {"x": 820, "y": 180},
                    "enabled": True,
                    "config": {},
                },
            ],
            "edges": [
                {"id": "e1", "source": "incoming", "target": "intent"},
                {"id": "e2", "source": "intent", "target": "kb"},
                {"id": "e3", "source": "kb", "target": "compose"},
                {"id": "e4", "source": "compose", "target": "handoff"},
            ],
        },
        "versions": [
            {
                "version": "v2.8",
                "status": "production",
                "editor": "Mock seed",
                "published_at": dt(days=-1).isoformat(),
                "change_summary": f"{name} operativo para pruebas",
            },
            {
                "version": "v2.7",
                "status": "archived",
                "editor": "Mock seed",
                "published_at": dt(days=-8).isoformat(),
                "change_summary": "Baseline de guardrails",
            },
        ],
        "scenarios": [
            {
                "id": "precio_sin_plan",
                "name": "Pide precio antes de plan",
                "status": "passed",
                "score": 94 - idx,
                "last_run_at": dt(minutes=-35).isoformat(),
            },
            {
                "id": "buro_malo",
                "name": "Pregunta por buro",
                "status": "warning" if idx % 2 else "passed",
                "score": 82 - idx,
                "last_run_at": dt(minutes=-58).isoformat(),
            },
            {
                "id": "pide_humano",
                "name": "Pide humano",
                "status": "passed",
                "score": 96,
                "last_run_at": dt(minutes=-12).isoformat(),
            },
            {
                "id": "documentos_incompletos",
                "name": "Documentos incompletos",
                "status": "risky" if role == "documentation" else "passed",
                "score": 78,
                "last_run_at": dt(minutes=-93).isoformat(),
            },
        ],
    }


def build_leads() -> list[dict[str, Any]]:
    random.seed(17)
    leads: list[dict[str, Any]] = []
    for i in range(42):
        first = FIRST_NAMES[i % len(FIRST_NAMES)]
        last = LAST_NAMES[(i * 3) % len(LAST_NAMES)]
        name = f"{first} {last}"
        model_sku, model_name, price, category, color, stock_status = MODELS[i % len(MODELS)]
        stage = STAGES[i % len(STAGES)]
        plan = PLANS[(i + 1) % len(PLANS)]
        source = SOURCES[(i * 2) % len(SOURCES)]
        city = CITIES[(i * 3) % len(CITIES)]
        risk = RISK_LEVELS[
            (i + (1 if stage in {"documentacion", "validacion"} else 0)) % len(RISK_LEVELS)
        ]
        docs_status = DOC_STATUSES[(i + 2) % len(DOC_STATUSES)]
        assigned_email = ADVISOR_EMAILS[i % len(ADVISOR_EMAILS)] if i % 5 != 2 else None
        status = CONV_STATUSES[i % len(CONV_STATUSES)]
        if stage in {"cierre_ganado", "cierre_perdido"}:
            status = "closed"
        score = max(
            18,
            min(
                99,
                46
                + (i * 7) % 54
                + (8 if stage in {"propuesta", "negociacion", "cita_agendada"} else 0),
            ),
        )
        health = max(15, min(99, 52 + (i * 5) % 45 - (12 if risk == "critical" else 0)))
        unread = 0 if status == "closed" else (i * 3) % 7
        minutes_ago = 8 + (i * 19) % 780
        intent = INTENTS[i % len(INTENTS)]
        has_handoff = i % 6 in {1, 4} or risk == "critical"
        has_followup = i % 3 != 0
        should_appoint = (
            stage in {"cita_agendada", "negociacion", "propuesta", "validacion"} or i % 4 == 0
        )
        tags = [MOCK_TAG, f"mock-lead-{i + 1:02d}", stage, source.lower().replace(" ", "_"), risk]
        if has_handoff:
            tags.append("handoff")
        if should_appoint:
            tags.append("appointment")
        if unread:
            tags.append("unread")
        leads.append(
            {
                "index": i + 1,
                "slug": f"mock-lead-{i + 1:02d}",
                "name": name,
                "phone": f"+521550010{i + 1:04d}",
                "email": f"{first.lower()}.{last.lower()}{i + 1:02d}@example.com",
                "score": score,
                "health": health,
                "risk": risk,
                "sla": SLA_STATUSES[i % len(SLA_STATUSES)],
                "stage": stage,
                "status": status,
                "source": source,
                "city": city,
                "assigned_email": assigned_email,
                "model_sku": model_sku,
                "model_name": model_name,
                "price": price,
                "category": category,
                "color": color,
                "stock_status": stock_status,
                "plan": plan,
                "tipo_credito": ["Bancario", "Nomina", "Contado", "Pyme"][i % 4],
                "income": 22000 + (i * 3700) % 98000,
                "antiguedad": ["6 meses", "1 ano", "2 anos", "4 anos", "Independiente"][i % 5],
                "preference": ["WhatsApp", "Llamada", "Email"][i % 3],
                "objection": ["Precio", "Enganche", "Tiempo", "Inventario", "Credito"][i % 5],
                "docs_status": docs_status,
                "unread": unread,
                "minutes_ago": minutes_ago,
                "last_intent": intent,
                "tags": tags,
                "has_handoff": has_handoff,
                "has_followup": has_followup,
                "should_appoint": should_appoint,
                "bot_paused": has_handoff and i % 2 == 0,
            }
        )
    return leads


LEADS = build_leads()


async def scalar(conn: AsyncConnection, sql: str, params: dict[str, Any] | None = None) -> Any:
    return (await conn.execute(text(sql), params or {})).scalar()


async def scalar_one(conn: AsyncConnection, sql: str, params: dict[str, Any] | None = None) -> Any:
    return (await conn.execute(text(sql), params or {})).scalar_one()


async def ensure_tenant(conn: AsyncConnection) -> UUID:
    tenant_id = await scalar(
        conn, "SELECT id FROM tenants WHERE name = :name", {"name": DEMO_TENANT_NAME}
    )
    tenant_config = {
        "mock_seed": MOCK_SEED,
        "demo": True,
        "business_name": "AtendIA Demo Motors",
        "phone_number": "+52 55 0100 1000",
        "phone_number_id": "mock_phone_number_id_2026",
        "meta": {
            "business_id": "mock_meta_business_2026",
            "phone_number_id": "mock_phone_number_id_2026",
            "display_phone_number": "+52 55 0100 1000",
            "waba_id": "mock_waba_2026",
            "verify_token": "mock_verify_token",
            "status": "connected",
        },
        "inbox_config": {
            **INBOX_CONFIG,
        },
    }
    if tenant_id is None:
        tenant_id = await scalar_one(
            conn,
            """
            INSERT INTO tenants (name, plan, status, meta_business_id, config, timezone, followups_enabled, is_demo)
            VALUES (:name, 'enterprise_mock', 'active', 'mock_meta_business_2026', CAST(:config AS jsonb), 'America/Mexico_City', true, true)
            RETURNING id
            """,
            {"name": DEMO_TENANT_NAME, "config": dumps(tenant_config)},
        )
        print(f"[OK] Created tenant {DEMO_TENANT_NAME} ({tenant_id})")
    else:
        await conn.execute(
            text(
                """
                UPDATE tenants
                SET plan = 'enterprise_mock',
                    status = 'active',
                    meta_business_id = 'mock_meta_business_2026',
                    config = COALESCE(config, '{}'::jsonb) || CAST(:config AS jsonb),
                    timezone = 'America/Mexico_City',
                    followups_enabled = true,
                    is_demo = true
                WHERE id = :tenant_id
                """
            ),
            {"tenant_id": tenant_id, "config": dumps(tenant_config)},
        )
        print(f"[--] Refreshed tenant {DEMO_TENANT_NAME} ({tenant_id})")
    return tenant_id


async def cleanup_mock(conn: AsyncConnection, tenant_id: UUID) -> None:
    await conn.execute(
        text(
            "DELETE FROM notifications WHERE tenant_id = :tenant_id AND source_type = 'mock_full_demo'"
        ),
        {"tenant_id": tenant_id},
    )
    await conn.execute(
        text(
            "DELETE FROM outbound_outbox WHERE tenant_id = :tenant_id AND idempotency_key LIKE 'mock-full:%'"
        ),
        {"tenant_id": tenant_id},
    )
    await conn.execute(
        text("DELETE FROM events WHERE tenant_id = :tenant_id AND payload->>'mock_seed' = :seed"),
        {"tenant_id": tenant_id, "seed": MOCK_SEED},
    )
    await conn.execute(
        text(
            "DELETE FROM followups_scheduled WHERE tenant_id = :tenant_id AND context->>'mock_seed' = :seed"
        ),
        {"tenant_id": tenant_id, "seed": MOCK_SEED},
    )
    await conn.execute(
        text(
            "DELETE FROM human_handoffs WHERE tenant_id = :tenant_id AND reason LIKE 'MOCK-FULL:%'"
        ),
        {"tenant_id": tenant_id},
    )
    await conn.execute(
        text("DELETE FROM appointments WHERE tenant_id = :tenant_id AND notes LIKE '[mock-full]%'"),
        {"tenant_id": tenant_id},
    )
    await conn.execute(
        text(
            "DELETE FROM conversations WHERE tenant_id = :tenant_id AND tags @> CAST(:tag AS jsonb)"
        ),
        {"tenant_id": tenant_id, "tag": dumps([MOCK_TAG])},
    )
    await conn.execute(
        text(
            "DELETE FROM customers WHERE tenant_id = :tenant_id AND (tags @> CAST(:tag AS jsonb) OR attrs->>'mock_seed' = :seed)"
        ),
        {"tenant_id": tenant_id, "tag": dumps([MOCK_TAG]), "seed": MOCK_SEED},
    )

    await conn.execute(
        text(
            "DELETE FROM kb_versions WHERE tenant_id = :tenant_id AND change_summary LIKE '[mock-full]%'"
        ),
        {"tenant_id": tenant_id},
    )
    await conn.execute(
        text("DELETE FROM kb_conflicts WHERE tenant_id = :tenant_id AND title LIKE '[Mock]%'"),
        {"tenant_id": tenant_id},
    )
    await conn.execute(
        text(
            "DELETE FROM kb_unanswered_questions WHERE tenant_id = :tenant_id AND query_normalized LIKE 'mock-full:%'"
        ),
        {"tenant_id": tenant_id},
    )
    await conn.execute(
        text("DELETE FROM kb_test_cases WHERE tenant_id = :tenant_id AND name LIKE '[Mock]%'"),
        {"tenant_id": tenant_id},
    )
    await conn.execute(
        text(
            "DELETE FROM kb_health_snapshots WHERE tenant_id = :tenant_id AND score_components->>'mock_seed' = :seed"
        ),
        {"tenant_id": tenant_id, "seed": MOCK_SEED},
    )
    await conn.execute(
        text(
            "DELETE FROM kb_source_priority_rules WHERE tenant_id = :tenant_id AND agent LIKE '[Mock]%'"
        ),
        {"tenant_id": tenant_id},
    )
    await conn.execute(
        text(
            "DELETE FROM kb_agent_permissions WHERE tenant_id = :tenant_id AND agent LIKE '[Mock]%'"
        ),
        {"tenant_id": tenant_id},
    )
    await conn.execute(
        text(
            "DELETE FROM knowledge_documents WHERE tenant_id = :tenant_id AND filename LIKE 'mock-full-%'"
        ),
        {"tenant_id": tenant_id},
    )
    await conn.execute(
        text(
            "DELETE FROM knowledge_base_sources WHERE tenant_id = :tenant_id AND name LIKE '[Mock]%'"
        ),
        {"tenant_id": tenant_id},
    )
    await conn.execute(
        text(
            "DELETE FROM tenant_faqs WHERE tenant_id = :tenant_id AND tags @> CAST(:tag AS jsonb)"
        ),
        {"tenant_id": tenant_id, "tag": dumps([MOCK_TAG])},
    )
    await conn.execute(
        text(
            "DELETE FROM tenant_catalogs WHERE tenant_id = :tenant_id AND tags @> CAST(:tag AS jsonb)"
        ),
        {"tenant_id": tenant_id, "tag": dumps([MOCK_TAG])},
    )
    await conn.execute(
        text("DELETE FROM whatsapp_templates WHERE tenant_id = :tenant_id AND name LIKE 'mock_%'"),
        {"tenant_id": tenant_id},
    )
    await conn.execute(
        text("DELETE FROM ai_agents WHERE tenant_id = :tenant_id AND name LIKE '[Mock]%'"),
        {"tenant_id": tenant_id},
    )
    await conn.execute(
        text("DELETE FROM advisor_pools WHERE tenant_id = :tenant_id AND name LIKE '[Mock]%'"),
        {"tenant_id": tenant_id},
    )
    await conn.execute(
        text(
            "DELETE FROM business_hours_rules WHERE tenant_id = :tenant_id AND name LIKE '[Mock]%'"
        ),
        {"tenant_id": tenant_id},
    )
    await conn.execute(
        text("DELETE FROM safety_rules WHERE tenant_id = :tenant_id AND key LIKE 'mock_%'"),
        {"tenant_id": tenant_id},
    )
    await conn.execute(
        text("DELETE FROM workflows WHERE tenant_id = :tenant_id AND name LIKE '[Mock]%'"),
        {"tenant_id": tenant_id},
    )
    await conn.execute(
        text("DELETE FROM agents WHERE tenant_id = :tenant_id AND name LIKE '[Mock]%'"),
        {"tenant_id": tenant_id},
    )
    print("[OK] Removed previous mock-full rows")


async def ensure_users(conn: AsyncConnection, tenant_id: UUID) -> dict[str, UUID]:
    result: dict[str, UUID] = {}
    password_hash = hash_password(DEMO_PASSWORD)
    for email, role, _name in USERS:
        user_id = await scalar(
            conn,
            "SELECT id FROM tenant_users WHERE tenant_id = :tenant_id AND email = :email ORDER BY created_at DESC LIMIT 1",
            {"tenant_id": tenant_id, "email": email},
        )
        if user_id is None:
            user_id = await scalar_one(
                conn,
                """
                INSERT INTO tenant_users (tenant_id, email, role, password_hash)
                VALUES (:tenant_id, :email, :role, :password_hash)
                RETURNING id
                """,
                {
                    "tenant_id": tenant_id,
                    "email": email,
                    "role": role,
                    "password_hash": password_hash,
                },
            )
        else:
            await conn.execute(
                text(
                    "UPDATE tenant_users SET role = :role, password_hash = :password_hash WHERE id = :user_id"
                ),
                {"user_id": user_id, "role": role, "password_hash": password_hash},
            )
        result[email] = user_id
    print(f"[OK] Users ready: {len(result)} (password {DEMO_PASSWORD})")
    return result


async def ensure_pipeline_branding_and_tools(
    conn: AsyncConnection, tenant_id: UUID, user_ids: dict[str, UUID]
) -> None:
    await conn.execute(
        text("UPDATE tenant_pipelines SET active = false WHERE tenant_id = :tenant_id"),
        {"tenant_id": tenant_id},
    )
    await conn.execute(
        text(
            """
            INSERT INTO tenant_pipelines (tenant_id, version, definition, active)
            VALUES (:tenant_id, 20260511, CAST(:definition AS jsonb), true)
            ON CONFLICT (tenant_id, version) DO UPDATE SET definition = EXCLUDED.definition, active = true
            """
        ),
        {"tenant_id": tenant_id, "definition": dumps(PIPELINE_DEFINITION)},
    )
    await conn.execute(
        text(
            """
            INSERT INTO tenant_branding (tenant_id, bot_name, voice, default_messages)
            VALUES (:tenant_id, 'AtenIA Demo', CAST(:voice AS jsonb), CAST(:messages AS jsonb))
            ON CONFLICT (tenant_id) DO UPDATE SET bot_name = EXCLUDED.bot_name, voice = EXCLUDED.voice, default_messages = EXCLUDED.default_messages
            """
        ),
        {
            "tenant_id": tenant_id,
            "voice": dumps(
                {
                    "tone": "claro",
                    "style": "asesor comercial",
                    "locale": "es-MX",
                    "mock_seed": MOCK_SEED,
                }
            ),
            "messages": dumps(
                {
                    "fallback": "Te conecto con un asesor para validarlo.",
                    "handoff": "Ya avise al equipo humano.",
                    "mock_seed": MOCK_SEED,
                }
            ),
        },
    )
    for tool_name, enabled, config in [
        ("quote", True, {"currency": "MXN", "requires_catalog": True, "mock_seed": MOCK_SEED}),
        ("search_catalog", True, {"max_results": 5, "respect_stock": True, "mock_seed": MOCK_SEED}),
        ("lookup_faq", True, {"min_score": 0.72, "mock_seed": MOCK_SEED}),
        ("book_appointment", True, {"default_duration_minutes": 60, "mock_seed": MOCK_SEED}),
        ("escalate", True, {"sla_minutes": 20, "mock_seed": MOCK_SEED}),
        ("followup", True, {"quiet_hours": ["21:00", "09:00"], "mock_seed": MOCK_SEED}),
        (
            "vision",
            True,
            {"allowed_documents": ["ine", "comprobante", "nomina"], "mock_seed": MOCK_SEED},
        ),
    ]:
        await conn.execute(
            text(
                """
                INSERT INTO tenant_tools_config (tenant_id, tool_name, enabled, config)
                VALUES (:tenant_id, :tool_name, :enabled, CAST(:config AS jsonb))
                ON CONFLICT (tenant_id, tool_name) DO UPDATE SET enabled = EXCLUDED.enabled, config = EXCLUDED.config
                """
            ),
            {
                "tenant_id": tenant_id,
                "tool_name": tool_name,
                "enabled": enabled,
                "config": dumps(config),
            },
        )
    print("[OK] Pipeline, branding and tool config ready")


async def ensure_field_definitions(conn: AsyncConnection, tenant_id: UUID) -> dict[str, UUID]:
    ids: dict[str, UUID] = {}
    for order, (key, label, field_type, options) in enumerate(FIELD_DEFINITIONS):
        field_id = await scalar_one(
            conn,
            """
            INSERT INTO customer_field_definitions (id, tenant_id, key, label, field_type, field_options, ordering)
            VALUES (gen_random_uuid(), :tenant_id, :key, :label, :field_type, CAST(:options AS jsonb), :ordering)
            ON CONFLICT (tenant_id, key) DO UPDATE SET
                label = EXCLUDED.label,
                field_type = EXCLUDED.field_type,
                field_options = EXCLUDED.field_options,
                ordering = EXCLUDED.ordering
            RETURNING id
            """,
            {
                "tenant_id": tenant_id,
                "key": key,
                "label": label,
                "field_type": field_type,
                "options": dumps(options) if options is not None else "null",
                "ordering": order,
            },
        )
        ids[key] = field_id
    print(f"[OK] Customer fields ready: {len(ids)}")
    return ids


async def ensure_agents(conn: AsyncConnection, tenant_id: UUID) -> dict[str, UUID]:
    agent_ids: dict[str, UUID] = {}
    for idx, (name, role, goal, intents) in enumerate(AGENT_SPECS):
        agent_id = await scalar_one(
            conn,
            """
            INSERT INTO agents (
                tenant_id, name, role, status, behavior_mode, version, dealership_id, branch_id,
                goal, style, tone, language, max_sentences, no_emoji, return_to_flow, is_default,
                system_prompt, active_intents, extraction_config, auto_actions, knowledge_config,
                flow_mode_rules, ops_config
            )
            VALUES (
                :tenant_id, :name, :role, :status, :mode, :version, 'demo-motors', :branch_id,
                :goal, :style, 'amigable', 'es-MX', :max_sentences, false, true, :is_default,
                :system_prompt, CAST(:intents AS jsonb), CAST(:extraction AS jsonb), CAST(:auto_actions AS jsonb),
                CAST(:knowledge AS jsonb), CAST(:flow_rules AS jsonb), CAST(:ops_config AS jsonb)
            )
            RETURNING id
            """,
            {
                "tenant_id": tenant_id,
                "name": name,
                "role": role,
                "status": "production" if idx < 4 else "testing",
                "mode": "strict" if role in {"documentation", "custom"} else "normal",
                "version": f"v2.{8 - idx}",
                "branch_id": f"branch-{idx + 1}",
                "goal": goal,
                "style": "Respuestas compactas, utiles y con derivacion humana cuando falte evidencia.",
                "max_sentences": 4,
                "is_default": False,
                "system_prompt": f"Eres {name}. Usa solo datos publicados y respeta los guardrails mock.",
                "intents": dumps(intents),
                "extraction": dumps(
                    {
                        "required_fields": ["modelo_interes", "plan_credito", "ciudad"],
                        "mock_seed": MOCK_SEED,
                    }
                ),
                "auto_actions": dumps(
                    {
                        "schedule_followup": True,
                        "create_handoff_on_risk": True,
                        "mock_seed": MOCK_SEED,
                    }
                ),
                "knowledge": dumps(
                    {
                        "collections": ["credito", "catalogo", "inventario"],
                        "min_score": 0.72,
                        "mock_seed": MOCK_SEED,
                    }
                ),
                "flow_rules": dumps(
                    {
                        "fallback_mode": "SUPPORT",
                        "handoff_on_confidence_below": 0.62,
                        "mock_seed": MOCK_SEED,
                    }
                ),
                "ops_config": dumps(build_agent_ops(name, role, idx)),
            },
        )
        agent_ids[name] = agent_id
    print(f"[OK] Agents ready: {len(agent_ids)}")
    return agent_ids


async def seed_kb_collections(conn: AsyncConnection, tenant_id: UUID) -> dict[str, UUID]:
    specs = [
        (
            "credito",
            "Credito y financiamiento",
            "Reglas de credito, enganche y documentos.",
            "landmark",
            "#22c55e",
        ),
        (
            "catalogo",
            "Catalogo vehicular",
            "Modelos, versiones, precios y stock mock.",
            "car",
            "#0ea5e9",
        ),
        (
            "inventario",
            "Inventario por sucursal",
            "Disponibilidad, colores y tiempos estimados.",
            "warehouse",
            "#f59e0b",
        ),
        (
            "postventa",
            "Postventa y servicio",
            "Garantias, servicios y agenda de taller.",
            "wrench",
            "#8b5cf6",
        ),
        (
            "policies",
            "Politicas comerciales",
            "Reglas de privacidad, consentimiento y seguridad.",
            "shield",
            "#ef4444",
        ),
        (
            "scripts",
            "Scripts de ventas",
            "Mensajes aprobados por etapa del embudo.",
            "message_square",
            "#14b8a6",
        ),
    ]
    ids: dict[str, UUID] = {}
    for slug, name, desc, icon, color in specs:
        collection_id = await scalar_one(
            conn,
            """
            INSERT INTO kb_collections (tenant_id, slug, name, description, icon, color)
            VALUES (:tenant_id, :slug, :name, :description, :icon, :color)
            ON CONFLICT (tenant_id, slug) DO UPDATE SET name = EXCLUDED.name, description = EXCLUDED.description, icon = EXCLUDED.icon, color = EXCLUDED.color
            RETURNING id
            """,
            {
                "tenant_id": tenant_id,
                "slug": slug,
                "name": name,
                "description": desc,
                "icon": icon,
                "color": color,
            },
        )
        ids[slug] = collection_id
    return ids


async def seed_faqs_and_catalog(
    conn: AsyncConnection, tenant_id: UUID, user_ids: dict[str, UUID], collections: dict[str, UUID]
) -> tuple[list[UUID], list[UUID]]:
    admin_id = user_ids["admin@demo.com"]
    faq_ids: list[UUID] = []
    faq_templates = [
        (
            "Que documentos necesito para Plan 10%?",
            "Para Plan 10% se solicita INE, comprobante de domicilio y recibo de nomina reciente.",
        ),
        (
            "Puedo apartar una unidad por WhatsApp?",
            "Si, se puede registrar interes y un asesor confirma condiciones de apartado antes de cualquier pago.",
        ),
        (
            "Que pasa si tengo buro negativo?",
            "No prometemos aprobacion. Podemos revisar alternativas y un asesor valida el caso con documentacion.",
        ),
        (
            "Cuanto dura una prueba de manejo?",
            "La prueba de manejo mock dura 45 a 60 minutos y requiere cita confirmada.",
        ),
        (
            "Puedo hacer todo el proceso en linea?",
            "La pre-calificacion y envio de documentos puede iniciar en linea; firma y entrega dependen del asesor.",
        ),
        (
            "Tienen garantia?",
            "Los vehiculos nuevos incluyen garantia de fabrica segun manual y poliza vigente.",
        ),
        (
            "Aceptan auto a cuenta?",
            "El asesor puede iniciar una valuacion, pero el monto final se confirma en sucursal.",
        ),
        (
            "Que horarios tienen?",
            "Horario demo: lunes a viernes 9:00 a 19:00 y sabado 10:00 a 16:00.",
        ),
        (
            "Pueden cotizar mensualidad?",
            "Solo se comparte estimado con plan y enganche capturados; la oferta final la valida el asesor.",
        ),
        (
            "Que pasa si me faltan documentos?",
            "Se mantiene el lead en documentacion y se agenda seguimiento automatico.",
        ),
        (
            "Como actualizo mi cita?",
            "Un asesor puede confirmar, reprogramar o cancelar la cita desde el command center.",
        ),
        (
            "Que sucursales participan?",
            "CDMX, Guadalajara, Monterrey, Puebla y Queretaro estan habilitadas en el demo.",
        ),
        (
            "Se puede reservar color?",
            "La reserva de color depende del inventario publicado y confirmacion humana.",
        ),
        (
            "Que modelos tienen entrega inmediata?",
            "City Sport, HR-V EXL, CR-V Turbo y BR-V Prime tienen unidades mock en stock.",
        ),
        (
            "Como se maneja privacidad?",
            "Solo se usan datos necesarios para atencion comercial y seguimiento, con consentimiento del cliente.",
        ),
        (
            "Que hago si la IA no sabe responder?",
            "El bot debe escalar a humano y no inventar precios, stock o aprobaciones.",
        ),
        (
            "Hay promociones por nomina?",
            "Hay rutas de credito por nomina, pero requisitos y elegibilidad se validan con el asesor.",
        ),
        (
            "Que es un handoff?",
            "Es una derivacion a operador humano cuando hay riesgo, baja confianza o solicitud explicita.",
        ),
        (
            "Cuantos mensajes de seguimiento se envian?",
            "El demo respeta maximo tres seguimientos automaticos en 24 horas.",
        ),
        (
            "Puedo comprar de contado?",
            "Si, el flujo de contado requiere INE, comprobante y validacion de disponibilidad.",
        ),
        (
            "Que pasa con citas no show?",
            "Se marca no show, se registra riesgo y se agenda reactivacion si aplica.",
        ),
        (
            "Como se validan documentos?",
            "El demo marca documentos como recibidos, revisados, rechazados o faltantes.",
        ),
        (
            "Hay leasing para empresas?",
            "Leasing pyme existe como plan mock y requiere datos fiscales adicionales.",
        ),
        (
            "El precio incluye placas?",
            "No se debe afirmar. El asesor confirma cargos, placas y seguros segun entidad.",
        ),
    ]
    for idx, (question, answer) in enumerate(faq_templates, start=1):
        collection_slug = ["credito", "catalogo", "postventa", "policies", "scripts"][idx % 5]
        faq_id = await scalar_one(
            conn,
            """
            INSERT INTO tenant_faqs (
                tenant_id, question, answer, tags, status, visibility, priority, created_by, updated_by,
                agent_permissions, collection_id, language
            )
            VALUES (
                :tenant_id, :question, :answer, CAST(:tags AS jsonb), :status, 'agents', :priority, :user_id, :user_id,
                CAST(:agent_permissions AS jsonb), :collection_id, 'es-MX'
            )
            ON CONFLICT (tenant_id, question) DO UPDATE SET
                answer = EXCLUDED.answer,
                tags = EXCLUDED.tags,
                status = EXCLUDED.status,
                priority = EXCLUDED.priority,
                updated_by = EXCLUDED.updated_by,
                collection_id = EXCLUDED.collection_id
            RETURNING id
            """,
            {
                "tenant_id": tenant_id,
                "question": f"[Mock] {question}",
                "answer": answer,
                "tags": dumps([MOCK_TAG, collection_slug, "faq", f"faq-{idx:02d}"]),
                "status": "published" if idx % 7 else "draft",
                "priority": 100 - idx,
                "user_id": admin_id,
                "agent_permissions": dumps(["[Mock] Sales Agent", "[Mock] Duda General"]),
                "collection_id": collections[collection_slug],
            },
        )
        faq_ids.append(faq_id)

    catalog_ids: list[UUID] = []
    for idx, (sku, name, price, category, color, stock_status) in enumerate(MODELS, start=1):
        for branch in ["CDMX", "Monterrey"] if idx <= 4 else ["Guadalajara"]:
            item_sku = f"{sku}-{branch.upper()}"
            catalog_id = await scalar_one(
                conn,
                """
                INSERT INTO tenant_catalogs (
                    tenant_id, sku, name, attrs, tags, active, category, status, visibility, priority,
                    created_by, updated_by, agent_permissions, collection_id, language, price_cents,
                    stock_status, region, branch, payment_plans
                )
                VALUES (
                    :tenant_id, :sku, :name, CAST(:attrs AS jsonb), CAST(:tags AS jsonb), true,
                    :category, 'published', 'agents', :priority, :user_id, :user_id,
                    CAST(:agent_permissions AS jsonb), :collection_id, 'es-MX', :price_cents,
                    :stock_status, 'MX', :branch, CAST(:plans AS jsonb)
                )
                ON CONFLICT (tenant_id, sku) DO UPDATE SET
                    name = EXCLUDED.name,
                    attrs = EXCLUDED.attrs,
                    tags = EXCLUDED.tags,
                    active = true,
                    category = EXCLUDED.category,
                    status = EXCLUDED.status,
                    priority = EXCLUDED.priority,
                    updated_by = EXCLUDED.updated_by,
                    collection_id = EXCLUDED.collection_id,
                    price_cents = EXCLUDED.price_cents,
                    stock_status = EXCLUDED.stock_status,
                    branch = EXCLUDED.branch,
                    payment_plans = EXCLUDED.payment_plans
                RETURNING id
                """,
                {
                    "tenant_id": tenant_id,
                    "sku": item_sku,
                    "name": f"[Mock] {name} {branch}",
                    "attrs": dumps(
                        {
                            "model": name,
                            "color": color,
                            "year": 2026,
                            "mock_seed": MOCK_SEED,
                            "price_mxn": price,
                            "stock_units": 1 + idx % 5,
                        }
                    ),
                    "tags": dumps([MOCK_TAG, "catalog", category.lower(), branch.lower()]),
                    "category": category,
                    "priority": 90 - idx,
                    "user_id": admin_id,
                    "agent_permissions": dumps(["[Mock] Sales Agent"]),
                    "collection_id": collections["catalogo"],
                    "price_cents": price * 100,
                    "stock_status": stock_status,
                    "branch": branch,
                    "plans": dumps(
                        [
                            {"name": plan, "down_payment_percent": [10, 15, 100, 12][pidx]}
                            for pidx, plan in enumerate(PLANS)
                        ]
                    ),
                },
            )
            catalog_ids.append(catalog_id)
    print(f"[OK] FAQs/catalog ready: {len(faq_ids)} FAQs, {len(catalog_ids)} catalog items")
    return faq_ids, catalog_ids


async def seed_knowledge_documents(
    conn: AsyncConnection, tenant_id: UUID, user_ids: dict[str, UUID], collections: dict[str, UUID]
) -> list[UUID]:
    admin_id = user_ids["admin@demo.com"]
    docs = [
        ("credito-plan-10", "credito", "Politica Plan 10% y requisitos minimos", 6),
        ("credito-bancario", "credito", "Matriz de credito bancario y excepciones", 7),
        ("inventario-sucursales", "inventario", "Inventario disponible por sucursal mock", 8),
        ("precios-promos", "catalogo", "Precios publicados y promociones vigentes", 6),
        ("postventa-garantia", "postventa", "Garantia y servicio postventa", 5),
        (
            "privacidad-consentimiento",
            "policies",
            "Politica de privacidad y consentimiento WhatsApp",
            5,
        ),
        ("scripts-reactivacion", "scripts", "Scripts aprobados para reactivacion", 6),
        ("scripts-handoff", "scripts", "Scripts de handoff y baja confianza", 5),
        ("leasing-pyme", "credito", "Leasing pyme y documentos fiscales", 5),
        ("no-show-recovery", "scripts", "Recuperacion de citas no show", 5),
    ]
    doc_ids: list[UUID] = []
    for idx, (slug, collection_slug, title, chunk_count) in enumerate(docs, start=1):
        doc_id = await scalar_one(
            conn,
            """
            INSERT INTO knowledge_documents (
                tenant_id, filename, storage_path, category, status, fragment_count, visibility, priority,
                created_by, updated_by, agent_permissions, collection_id, language, progress_percentage,
                embedded_chunk_count, error_count
            )
            VALUES (
                :tenant_id, :filename, :storage_path, :category, :status, :fragment_count, 'agents', :priority,
                :user_id, :user_id, CAST(:agent_permissions AS jsonb), :collection_id, 'es-MX', :progress,
                :embedded_count, :error_count
            )
            RETURNING id
            """,
            {
                "tenant_id": tenant_id,
                "filename": f"mock-full-{slug}.pdf",
                "storage_path": f"mock://knowledge/{slug}.pdf",
                "category": collection_slug,
                "status": "indexed" if idx % 6 else "processing",
                "fragment_count": chunk_count,
                "priority": 80 - idx,
                "user_id": admin_id,
                "agent_permissions": dumps(
                    ["[Mock] Sales Agent", "[Mock] Duda General", "[Mock] Supervisor IA"]
                ),
                "collection_id": collections[collection_slug],
                "progress": 100 if idx % 6 else 67,
                "embedded_count": chunk_count if idx % 6 else chunk_count - 2,
                "error_count": 0 if idx % 6 else 1,
            },
        )
        doc_ids.append(doc_id)
        for chunk_idx in range(chunk_count):
            await conn.execute(
                text(
                    """
                    INSERT INTO knowledge_chunks (
                        document_id, tenant_id, chunk_index, text, chunk_status, marked_critical,
                        token_count, page, heading, section, last_retrieved_at, retrieval_count, average_score
                    )
                    VALUES (
                        :document_id, :tenant_id, :chunk_index, :body, :status, :critical,
                        :token_count, :page, :heading, :section, :retrieved_at, :retrieval_count, :average_score
                    )
                    """
                ),
                {
                    "document_id": doc_id,
                    "tenant_id": tenant_id,
                    "chunk_index": chunk_idx,
                    "body": f"[mock-full] {title}. Seccion {chunk_idx + 1}: regla operativa para probar recuperacion RAG, fuentes, conflictos y citas. No inventar precios ni aprobaciones.",
                    "status": "embedded" if chunk_idx % 5 else "needs_review",
                    "critical": chunk_idx in {0, 3},
                    "token_count": 145 + chunk_idx * 18,
                    "page": chunk_idx + 1,
                    "heading": title,
                    "section": f"Seccion {chunk_idx + 1}",
                    "retrieved_at": dt(minutes=-(idx * 13 + chunk_idx * 5)),
                    "retrieval_count": 3 + idx * chunk_idx,
                    "average_score": round(0.71 + (chunk_idx % 4) * 0.06, 2),
                },
            )
    print(f"[OK] Knowledge documents ready: {len(doc_ids)} docs")
    return doc_ids


async def seed_kb_ops(
    conn: AsyncConnection,
    tenant_id: UUID,
    user_ids: dict[str, UUID],
    collections: dict[str, UUID],
    faq_ids: list[UUID],
    catalog_ids: list[UUID],
    doc_ids: list[UUID],
) -> None:
    admin_id = user_ids["admin@demo.com"]
    reviewer_id = user_ids["marta.nunez@demo.com"]
    for entity_type, ids in [
        ("faq", faq_ids[:8]),
        ("catalog", catalog_ids[:6]),
        ("document", doc_ids[:6]),
    ]:
        for idx, entity_id in enumerate(ids, start=1):
            await conn.execute(
                text(
                    """
                    INSERT INTO kb_versions (tenant_id, entity_type, entity_id, version_number, changed_by, change_summary, diff_json)
                    VALUES (:tenant_id, :entity_type, :entity_id, :version_number, :changed_by, :summary, CAST(:diff AS jsonb))
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "entity_type": entity_type,
                    "entity_id": entity_id,
                    "version_number": idx,
                    "changed_by": admin_id,
                    "summary": f"[mock-full] Version seeded for {entity_type} {idx}",
                    "diff": dumps(
                        {"mock_seed": MOCK_SEED, "fields": ["status", "priority", "content"]}
                    ),
                },
            )

    for idx in range(8):
        await conn.execute(
            text(
                """
                INSERT INTO kb_conflicts (
                    tenant_id, title, detection_type, severity, status, entity_a_type, entity_a_id,
                    entity_a_excerpt, entity_b_type, entity_b_id, entity_b_excerpt, suggested_priority,
                    assigned_to, resolved_by, resolved_at, resolution_action
                )
                VALUES (
                    :tenant_id, :title, :detection_type, :severity, :status, :a_type, :a_id,
                    :a_excerpt, :b_type, :b_id, :b_excerpt, :priority,
                    :assigned_to, :resolved_by, :resolved_at, :resolution_action
                )
                """
            ),
            {
                "tenant_id": tenant_id,
                "title": f"[Mock] Conflicto {idx + 1}: precio o requisito inconsistente",
                "detection_type": ["price", "policy", "stock", "documents"][idx % 4],
                "severity": ["high", "medium", "critical", "low"][idx % 4],
                "status": "resolved" if idx % 5 == 0 else "open",
                "a_type": "faq",
                "a_id": faq_ids[idx % len(faq_ids)],
                "a_excerpt": "FAQ indica requisito anterior.",
                "b_type": "document",
                "b_id": doc_ids[idx % len(doc_ids)],
                "b_excerpt": "Documento operativo indica requisito actualizado.",
                "priority": "Priorizar documento publicado mas reciente.",
                "assigned_to": reviewer_id,
                "resolved_by": reviewer_id if idx % 5 == 0 else None,
                "resolved_at": dt(days=-idx) if idx % 5 == 0 else None,
                "resolution_action": "accepted_document" if idx % 5 == 0 else None,
            },
        )

    for idx in range(14):
        conv_id = None
        await conn.execute(
            text(
                """
                INSERT INTO kb_unanswered_questions (
                    tenant_id, query, query_normalized, agent, conversation_id, top_score, llm_confidence,
                    escalation_reason, failed_chunks, suggested_answer, status, assigned_to, linked_faq_id, resolved_at
                )
                VALUES (
                    :tenant_id, :query, :normalized, :agent, :conversation_id, :top_score, :confidence,
                    :reason, CAST(:failed_chunks AS jsonb), :suggested_answer, :status, :assigned_to, :linked_faq_id, :resolved_at
                )
                """
            ),
            {
                "tenant_id": tenant_id,
                "query": f"[Mock] El cliente pregunta caso no cubierto #{idx + 1}: precio con seguro incluido?",
                "normalized": f"mock-full:unanswered:{idx + 1:02d}",
                "agent": ["[Mock] Sales Agent", "[Mock] Duda General", "[Mock] Postventa"][idx % 3],
                "conversation_id": conv_id,
                "top_score": round(0.31 + idx * 0.025, 3),
                "confidence": ["low", "medium", "low"][idx % 3],
                "reason": "No hay fuente publicada suficiente.",
                "failed_chunks": dumps([{"source": "catalogo", "score": 0.34 + idx * 0.01}]),
                "suggested_answer": "Escalar a asesor y crear FAQ si se repite.",
                "status": "resolved" if idx % 6 == 0 else "open",
                "assigned_to": reviewer_id,
                "linked_faq_id": faq_ids[idx % len(faq_ids)] if idx % 6 == 0 else None,
                "resolved_at": dt(days=-idx) if idx % 6 == 0 else None,
            },
        )

    arr_text = PG_ARRAY(SAText())
    test_case_sql = text(
        """
        INSERT INTO kb_test_cases (
            tenant_id, name, user_query, expected_sources, expected_keywords, forbidden_phrases,
            agent, required_customer_fields, expected_action, minimum_score, is_critical, created_by
        )
        VALUES (
            :tenant_id, :name, :query, CAST(:sources AS jsonb), :keywords, :forbidden,
            :agent, :required_fields, :expected_action, :minimum_score, :critical, :created_by
        )
        RETURNING id
        """
    ).bindparams(
        bindparam("keywords", type_=arr_text),
        bindparam("forbidden", type_=arr_text),
        bindparam("required_fields", type_=arr_text),
    )
    test_run_sql = text(
        """
        INSERT INTO kb_test_runs (
            tenant_id, test_case_id, run_id, status, retrieved_sources, generated_answer,
            diff_vs_expected, duration_ms, failure_reasons
        )
        VALUES (
            :tenant_id, :test_case_id, :run_id, :status, CAST(:sources AS jsonb), :answer,
            CAST(:diff AS jsonb), :duration_ms, :failure_reasons
        )
        """
    ).bindparams(bindparam("failure_reasons", type_=arr_text))
    for idx in range(10):
        case_id = (
            await conn.execute(
                test_case_sql,
                {
                    "tenant_id": tenant_id,
                    "name": f"[Mock] KB regression {idx + 1:02d}",
                    "query": [
                        "Que documentos necesito?",
                        "Cotiza mensualidad HR-V",
                        "Hay stock en CDMX?",
                        "Tengo buro malo",
                        "Reagenda mi cita",
                    ][idx % 5],
                    "sources": dumps(["faq", "catalog", "document"]),
                    "keywords": ["documentos", "credito"] if idx % 2 else ["precio", "stock"],
                    "forbidden": ["aprobado", "garantizado", "seguro hay stock"],
                    "agent": ["[Mock] Sales Agent", "[Mock] Duda General"][idx % 2],
                    "required_fields": ["modelo_interes", "plan_credito"] if idx % 3 == 0 else [],
                    "expected_action": "handoff" if idx % 4 == 0 else "answer",
                    "minimum_score": 0.72,
                    "critical": idx % 4 == 0,
                    "created_by": admin_id,
                },
            )
        ).scalar_one()
        for run_idx in range(2):
            status = "passed" if (idx + run_idx) % 5 else "failed"
            await conn.execute(
                test_run_sql,
                {
                    "tenant_id": tenant_id,
                    "test_case_id": case_id,
                    "run_id": uuid4(),
                    "status": status,
                    "sources": dumps(
                        [
                            {
                                "id": str(doc_ids[(idx + run_idx) % len(doc_ids)]),
                                "score": 0.78 + run_idx * 0.04,
                            }
                        ]
                    ),
                    "answer": "Respuesta mock generada con fuentes publicadas y sin prometer aprobacion.",
                    "diff": dumps(
                        {
                            "mock_seed": MOCK_SEED,
                            "missing_keywords": [] if status == "passed" else ["stock"],
                        }
                    ),
                    "duration_ms": 420 + idx * 31 + run_idx * 22,
                    "failure_reasons": [] if status == "passed" else ["Falto keyword esperada"],
                },
            )

    for idx in range(10):
        await conn.execute(
            text(
                """
                INSERT INTO kb_health_snapshots (tenant_id, snapshot_at, score, score_components, main_risks, suggested_actions, per_collection_scores)
                VALUES (:tenant_id, :snapshot_at, :score, CAST(:components AS jsonb), CAST(:risks AS jsonb), CAST(:actions AS jsonb), CAST(:per_collection AS jsonb))
                """
            ),
            {
                "tenant_id": tenant_id,
                "snapshot_at": dt(days=-(9 - idx)),
                "score": 78 + idx * 2,
                "components": dumps(
                    {
                        "mock_seed": MOCK_SEED,
                        "retrieval": 80 + idx,
                        "freshness": 72 + idx,
                        "conflicts": 64 + idx,
                    }
                ),
                "risks": dumps(
                    ["conflictos abiertos", "stock desactualizado"]
                    if idx < 4
                    else ["sin bloqueos criticos"]
                ),
                "actions": dumps(
                    ["resolver conflictos", "actualizar catalogo", "reindexar documentos"]
                ),
                "per_collection": dumps(
                    {slug: 70 + ((idx + pos) % 20) for pos, slug in enumerate(collections)}
                ),
            },
        )

    permission_sql = text(
        """
        INSERT INTO kb_agent_permissions (
            tenant_id, agent, allowed_source_types, allowed_collection_slugs, min_score,
            can_quote_prices, can_quote_stock, required_customer_fields, escalate_on_conflict,
            fallback_message, updated_by
        )
        VALUES (
            :tenant_id, :agent, :source_types, :collection_slugs, :min_score,
            :can_quote_prices, :can_quote_stock, :required_fields, true,
            :fallback, :updated_by
        )
        ON CONFLICT (tenant_id, agent) DO UPDATE SET
            allowed_source_types = EXCLUDED.allowed_source_types,
            allowed_collection_slugs = EXCLUDED.allowed_collection_slugs,
            min_score = EXCLUDED.min_score,
            can_quote_prices = EXCLUDED.can_quote_prices,
            can_quote_stock = EXCLUDED.can_quote_stock,
            required_customer_fields = EXCLUDED.required_customer_fields,
            fallback_message = EXCLUDED.fallback_message,
            updated_by = EXCLUDED.updated_by
        """
    ).bindparams(
        bindparam("source_types", type_=arr_text),
        bindparam("collection_slugs", type_=arr_text),
        bindparam("required_fields", type_=arr_text),
    )
    for name, source_types, slugs, can_price, can_stock, required in [
        (
            "[Mock] Sales Agent",
            ["faq", "catalog", "document"],
            ["credito", "catalogo", "inventario", "scripts"],
            True,
            True,
            ["modelo_interes", "plan_credito"],
        ),
        (
            "[Mock] Duda General",
            ["faq", "document"],
            ["policies", "postventa", "scripts"],
            False,
            False,
            [],
        ),
        (
            "[Mock] Postventa",
            ["faq", "document"],
            ["postventa", "policies"],
            False,
            False,
            ["telefono"],
        ),
        (
            "[Mock] Supervisor IA",
            ["faq", "catalog", "document"],
            list(collections.keys()),
            True,
            True,
            [],
        ),
    ]:
        await conn.execute(
            permission_sql,
            {
                "tenant_id": tenant_id,
                "agent": name,
                "source_types": source_types,
                "collection_slugs": slugs,
                "min_score": 0.72,
                "can_quote_prices": can_price,
                "can_quote_stock": can_stock,
                "required_fields": required,
                "fallback": "Dejame validarlo con un asesor para darte informacion correcta.",
                "updated_by": admin_id,
            },
        )

    for agent in ["[Mock] Sales Agent", "[Mock] Duda General", "[Mock] Postventa"]:
        for idx, source_type in enumerate(["document", "faq", "catalog"]):
            await conn.execute(
                text(
                    """
                    INSERT INTO kb_source_priority_rules (
                        tenant_id, agent, source_type, priority, minimum_score, allow_synthesis,
                        allow_direct_answer, escalation_required_when_conflict
                    )
                    VALUES (:tenant_id, :agent, :source_type, :priority, :minimum_score, true, :direct, true)
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "agent": agent,
                    "source_type": source_type,
                    "priority": 100 - idx * 15,
                    "minimum_score": 0.7 + idx * 0.03,
                    "direct": idx != 0,
                },
            )

    await conn.execute(
        text(
            """
            INSERT INTO kb_safe_answer_settings (
                tenant_id, min_score_to_answer, escalate_on_conflict, block_invented_prices,
                block_invented_stock, risky_phrases, default_fallback_message, updated_by
            )
            VALUES (:tenant_id, 0.72, true, true, true, CAST(:phrases AS jsonb), :fallback, :updated_by)
            ON CONFLICT (tenant_id) DO UPDATE SET
                min_score_to_answer = EXCLUDED.min_score_to_answer,
                escalate_on_conflict = EXCLUDED.escalate_on_conflict,
                block_invented_prices = EXCLUDED.block_invented_prices,
                block_invented_stock = EXCLUDED.block_invented_stock,
                risky_phrases = EXCLUDED.risky_phrases,
                default_fallback_message = EXCLUDED.default_fallback_message,
                updated_by = EXCLUDED.updated_by
            """
        ),
        {
            "tenant_id": tenant_id,
            "phrases": dumps(
                ["ya estas aprobado", "te garantizo", "seguro hay stock", "tasa fija confirmada"]
            ),
            "fallback": "No tengo una fuente suficiente. Te conecto con un asesor para confirmarlo.",
            "updated_by": admin_id,
        },
    )
    print("[OK] KB operations data ready")


async def seed_customer_and_conversation(
    conn: AsyncConnection,
    tenant_id: UUID,
    user_ids: dict[str, UUID],
    field_ids: dict[str, UUID],
    agent_ids: dict[str, UUID],
    lead: dict[str, Any],
) -> tuple[UUID, UUID, list[UUID]]:
    assigned_user_id = user_ids.get(lead["assigned_email"]) if lead["assigned_email"] else None
    assigned_agent_id = (
        agent_ids.get("[Mock] Sales Agent")
        if lead["stage"] in {"propuesta", "negociacion", "cita_agendada"}
        else agent_ids.get("[Mock] Recepcionista IA")
    )
    last_activity_at = dt(minutes=-lead["minutes_ago"])
    next_action = {
        "nuevo_lead": "calificar",
        "calificacion": "capturar_plan",
        "documentacion": "pedir_documentos",
        "validacion": "revisar_documentos",
        "propuesta": "enviar_cotizacion",
        "negociacion": "resolver_objecion",
        "cita_agendada": "confirmar_cita",
        "cierre_ganado": "cerrar_expediente",
        "cierre_perdido": "reactivar",
    }[lead["stage"]]
    customer_id = await scalar_one(
        conn,
        """
        INSERT INTO customers (
            tenant_id, phone_e164, name, email, score, attrs, status, stage, source,
            tags, assigned_user_id, last_activity_at, health_score, risk_level, sla_status,
            next_best_action, ai_summary, ai_insight_reason, ai_confidence, documents_status,
            last_ai_action_at, last_human_action_at, updated_at
        )
        VALUES (
            :tenant_id, :phone, :name, :email, :score, CAST(:attrs AS jsonb), :status, :stage, :source,
            CAST(:tags AS jsonb), :assigned_user_id, :last_activity_at, :health, :risk, :sla,
            :next_action, :summary, :insight, :confidence, :docs_status,
            :last_ai, :last_human, now()
        )
        ON CONFLICT (tenant_id, phone_e164) DO UPDATE SET
            name = EXCLUDED.name,
            email = EXCLUDED.email,
            score = EXCLUDED.score,
            attrs = EXCLUDED.attrs,
            status = EXCLUDED.status,
            stage = EXCLUDED.stage,
            source = EXCLUDED.source,
            tags = EXCLUDED.tags,
            assigned_user_id = EXCLUDED.assigned_user_id,
            last_activity_at = EXCLUDED.last_activity_at,
            health_score = EXCLUDED.health_score,
            risk_level = EXCLUDED.risk_level,
            sla_status = EXCLUDED.sla_status,
            next_best_action = EXCLUDED.next_best_action,
            ai_summary = EXCLUDED.ai_summary,
            ai_insight_reason = EXCLUDED.ai_insight_reason,
            ai_confidence = EXCLUDED.ai_confidence,
            documents_status = EXCLUDED.documents_status,
            last_ai_action_at = EXCLUDED.last_ai_action_at,
            last_human_action_at = EXCLUDED.last_human_action_at,
            updated_at = now()
        RETURNING id
        """,
        {
            "tenant_id": tenant_id,
            "phone": lead["phone"],
            "name": lead["name"],
            "email": lead["email"],
            "score": lead["score"],
            "attrs": dumps(
                {
                    "mock_seed": MOCK_SEED,
                    "slug": lead["slug"],
                    "model_sku": lead["model_sku"],
                    "estimated_value": lead["price"],
                    "campaign": f"{lead['source']} {lead['model_name']}",
                    "city": lead["city"],
                }
            ),
            "status": "won"
            if lead["stage"] == "cierre_ganado"
            else ("lost" if lead["stage"] == "cierre_perdido" else "active"),
            "stage": lead["stage"],
            "source": lead["source"],
            "tags": dumps(lead["tags"]),
            "assigned_user_id": assigned_user_id,
            "last_activity_at": last_activity_at,
            "health": lead["health"],
            "risk": lead["risk"],
            "sla": lead["sla"],
            "next_action": next_action,
            "summary": f"{lead['name']} esta en {stage_label(lead['stage'])}, interesado en {lead['model_name']} con {lead['plan']}.",
            "insight": f"Mock: riesgo {lead['risk']}, SLA {lead['sla']} y objecion {lead['objection']}.",
            "confidence": round(0.61 + (lead["index"] % 35) / 100, 2),
            "docs_status": lead["docs_status"],
            "last_ai": last_activity_at - timedelta(minutes=3),
            "last_human": last_activity_at - timedelta(minutes=12) if assigned_user_id else None,
        },
    )

    for table in [
        "customer_scores",
        "customer_risks",
        "customer_next_best_actions",
        "customer_timeline_events",
        "customer_documents",
        "customer_ai_review_items",
        "customer_notes",
    ]:
        await conn.execute(
            text(f"DELETE FROM {table} WHERE customer_id = :customer_id"),
            {"customer_id": customer_id},
        )

    values = {
        "modelo_interes": lead["model_name"],
        "presupuesto": str(lead["price"]),
        "plan_credito": lead["plan"],
        "tipo_credito": lead["tipo_credito"],
        "ingreso_mensual": str(lead["income"]),
        "antiguedad_laboral": lead["antiguedad"],
        "ciudad": lead["city"],
        "preferencia_contacto": lead["preference"],
        "objecion_principal": lead["objection"],
        "fecha_cita_objetivo": dt(days=lead["index"] % 14 + 1).date().isoformat(),
        "docs_ine": "true" if lead["docs_status"] in {"partial", "complete"} else "false",
        "docs_comprobante": "true" if lead["docs_status"] == "complete" else "false",
        "docs_nomina": "true"
        if lead["tipo_credito"] == "Nomina" and lead["docs_status"] != "missing"
        else "false",
        "docs_estados_cuenta": "true"
        if lead["plan"] == "48 meses + 15% enganche" and lead["docs_status"] == "complete"
        else "false",
    }
    for key, value in values.items():
        await conn.execute(
            text(
                """
                INSERT INTO customer_field_values (customer_id, field_definition_id, value)
                VALUES (:customer_id, :field_id, :value)
                ON CONFLICT (customer_id, field_definition_id) DO UPDATE SET value = EXCLUDED.value, updated_at = now()
                """
            ),
            {"customer_id": customer_id, "field_id": field_ids[key], "value": value},
        )

    await conn.execute(
        text(
            """
            INSERT INTO customer_scores (
                id, tenant_id, customer_id, total_score, intent_score, activity_score, documentation_score,
                data_quality_score, conversation_engagement_score, stage_progress_score, abandonment_risk_score,
                explanation, calculated_at
            )
            VALUES (
                gen_random_uuid(), :tenant_id, :customer_id, :total, :intent, :activity, :docs, :quality, :engagement,
                :stage_score, :abandonment, CAST(:explanation AS jsonb), :calculated_at
            )
            """
        ),
        {
            "tenant_id": tenant_id,
            "customer_id": customer_id,
            "total": lead["score"],
            "intent": min(99, 55 + lead["index"] % 41),
            "activity": min(99, 40 + (lead["index"] * 3) % 58),
            "docs": {"missing": 20, "partial": 55, "complete": 92, "rejected": 35}[
                lead["docs_status"]
            ],
            "quality": min(99, 65 + lead["index"] % 25),
            "engagement": min(99, 50 + lead["unread"] * 6 + lead["index"] % 20),
            "stage_score": 30 + STAGES.index(lead["stage"]) * 8,
            "abandonment": 80
            if lead["sla"] == "breached"
            else (55 if lead["sla"] == "at_risk" else 20),
            "explanation": dumps(
                {
                    "mock_seed": MOCK_SEED,
                    "drivers": ["intent", "documents", "sla"],
                    "source": lead["source"],
                }
            ),
            "calculated_at": last_activity_at,
        },
    )
    for r_idx, risk_type in enumerate(
        ["sla", "documents"] if lead["risk"] in {"high", "critical"} else ["followup"]
    ):
        await conn.execute(
            text(
                """
                INSERT INTO customer_risks (id, tenant_id, customer_id, risk_type, severity, reason, recommended_action, status, created_at, resolved_at)
                VALUES (gen_random_uuid(), :tenant_id, :customer_id, :risk_type, :severity, :reason, :recommended_action, :status, :created_at, :resolved_at)
                """
            ),
            {
                "tenant_id": tenant_id,
                "customer_id": customer_id,
                "risk_type": risk_type,
                "severity": lead["risk"] if r_idx == 0 else "medium",
                "reason": f"Mock: {risk_type} requiere revision en etapa {lead['stage']}.",
                "recommended_action": f"Ejecutar accion {next_action} con prioridad.",
                "status": "resolved"
                if lead["stage"] in {"cierre_ganado", "cierre_perdido"}
                else "open",
                "created_at": last_activity_at - timedelta(hours=2 + r_idx),
                "resolved_at": last_activity_at
                if lead["stage"] in {"cierre_ganado", "cierre_perdido"}
                else None,
            },
        )
    for action_idx, action_type in enumerate([next_action, "enviar_mensaje", "crear_tarea"]):
        await conn.execute(
            text(
                """
                INSERT INTO customer_next_best_actions (
                    id, tenant_id, customer_id, action_type, priority, reason, confidence, suggested_message,
                    status, expires_at, created_at, executed_at
                )
                VALUES (
                    gen_random_uuid(), :tenant_id, :customer_id, :action_type, :priority, :reason, :confidence, :message,
                    :status, :expires_at, :created_at, :executed_at
                )
                """
            ),
            {
                "tenant_id": tenant_id,
                "customer_id": customer_id,
                "action_type": action_type,
                "priority": 95 - action_idx * 12 - lead["index"] % 10,
                "reason": f"Mock: accion sugerida por etapa {lead['stage']} y riesgo {lead['risk']}.",
                "confidence": round(0.74 + action_idx * 0.04, 2),
                "message": f"Hola {lead['name'].split()[0]}, te ayudo con {lead['model_name']} y el siguiente paso.",
                "status": "executed"
                if action_idx == 0 and lead["stage"] in {"cierre_ganado", "cierre_perdido"}
                else "active",
                "expires_at": dt(days=2),
                "created_at": last_activity_at - timedelta(minutes=45 + action_idx * 8),
                "executed_at": last_activity_at
                if action_idx == 0 and lead["stage"] in {"cierre_ganado", "cierre_perdido"}
                else None,
            },
        )

    timeline = [
        ("lead.created", "Lead creado", f"Origen {lead['source']}", "system"),
        ("message.received", "Mensaje recibido", f"Interes en {lead['model_name']}", "customer"),
        ("stage.changed", "Cambio de etapa", f"Ahora en {stage_label(lead['stage'])}", "system"),
        (
            "ai.summary",
            "Resumen IA generado",
            f"Riesgo {lead['risk']} y accion {next_action}",
            "ai",
        ),
    ]
    for pos, (event_type, title, description, actor_type) in enumerate(timeline):
        await conn.execute(
            text(
                """
                INSERT INTO customer_timeline_events (
                    id, tenant_id, customer_id, event_type, title, description, actor_type, actor_id, metadata_json, created_at
                )
                VALUES (gen_random_uuid(), :tenant_id, :customer_id, :event_type, :title, :description, :actor_type, :actor_id, CAST(:metadata AS jsonb), :created_at)
                """
            ),
            {
                "tenant_id": tenant_id,
                "customer_id": customer_id,
                "event_type": event_type,
                "title": title,
                "description": description,
                "actor_type": actor_type,
                "actor_id": assigned_user_id if actor_type == "user" else None,
                "metadata": dumps({"mock_seed": MOCK_SEED, "stage": lead["stage"]}),
                "created_at": last_activity_at - timedelta(hours=3 - pos),
            },
        )

    document_types = [
        ("ine", "INE"),
        ("comprobante", "Comprobante de domicilio"),
        ("nomina", "Recibo de nomina"),
        ("estado_cuenta", "Estado de cuenta"),
    ]
    for doc_idx, (doc_type, label) in enumerate(document_types):
        if lead["docs_status"] == "complete":
            status = "approved"
        elif lead["docs_status"] == "partial":
            status = "received" if doc_idx < 2 else "missing"
        elif lead["docs_status"] == "rejected":
            status = "rejected" if doc_idx == 0 else "missing"
        else:
            status = "missing"
        await conn.execute(
            text(
                """
                INSERT INTO customer_documents (
                    id, tenant_id, customer_id, document_type, label, status, file_url, uploaded_at,
                    reviewed_at, rejection_reason, created_at, updated_at
                )
                VALUES (
                    gen_random_uuid(), :tenant_id, :customer_id, :doc_type, :label, :status, :file_url, :uploaded_at,
                    :reviewed_at, :rejection_reason, :created_at, now()
                )
                """
            ),
            {
                "tenant_id": tenant_id,
                "customer_id": customer_id,
                "doc_type": doc_type,
                "label": label,
                "status": status,
                "file_url": f"mock://documents/{lead['slug']}/{doc_type}.jpg"
                if status != "missing"
                else None,
                "uploaded_at": last_activity_at - timedelta(hours=1, minutes=doc_idx * 7)
                if status != "missing"
                else None,
                "reviewed_at": last_activity_at - timedelta(minutes=doc_idx * 9)
                if status in {"approved", "rejected"}
                else None,
                "rejection_reason": "Imagen borrosa en seed mock" if status == "rejected" else None,
                "created_at": last_activity_at - timedelta(hours=2),
            },
        )

    await conn.execute(
        text(
            """
            INSERT INTO customer_notes (id, tenant_id, customer_id, author_user_id, content, source, pinned, created_at, updated_at)
            VALUES (gen_random_uuid(), :tenant_id, :customer_id, :author_id, :content, 'mock_full', true, :created_at, now())
            """
        ),
        {
            "tenant_id": tenant_id,
            "customer_id": customer_id,
            "author_id": assigned_user_id or user_ids["admin@demo.com"],
            "content": f"[mock-full] {lead['name']} interesado en {lead['model_name']}. Objecion: {lead['objection']}. Siguiente accion: {next_action}.",
            "created_at": last_activity_at - timedelta(minutes=20),
        },
    )

    conv_id = await scalar_one(
        conn,
        """
        INSERT INTO conversations (
            tenant_id, customer_id, channel, status, current_stage, last_activity_at,
            assigned_user_id, assigned_agent_id, unread_count, tags
        )
        VALUES (
            :tenant_id, :customer_id, 'whatsapp_meta', :status, :stage, :last_activity_at,
            :assigned_user_id, :assigned_agent_id, :unread, CAST(:tags AS jsonb)
        )
        RETURNING id
        """,
        {
            "tenant_id": tenant_id,
            "customer_id": customer_id,
            "status": lead["status"],
            "stage": lead["stage"],
            "last_activity_at": last_activity_at,
            "assigned_user_id": assigned_user_id,
            "assigned_agent_id": assigned_agent_id,
            "unread": lead["unread"],
            "tags": dumps(lead["tags"]),
        },
    )
    extracted = {
        "mock_seed": MOCK_SEED,
        "nombre": {"value": lead["name"], "confidence": 0.98},
        "modelo_interes": {"value": lead["model_name"], "confidence": 0.91},
        "plan_credito": {"value": lead["plan"], "confidence": 0.84},
        "ciudad": {"value": lead["city"], "confidence": 0.86},
        "presupuesto": {"value": lead["price"], "confidence": 0.79},
        "docs_ine": values["docs_ine"] == "true",
        "docs_comprobante": values["docs_comprobante"] == "true",
    }
    await conn.execute(
        text(
            """
            INSERT INTO conversation_state (
                conversation_id, extracted_data, pending_confirmation, last_intent, stage_entered_at,
                followups_sent_count, total_cost_usd, bot_paused, updated_at
            )
            VALUES (
                :conversation_id, CAST(:extracted AS jsonb), :pending_confirmation, :intent, :stage_entered_at,
                :followups_sent, :cost, :bot_paused, now()
            )
            ON CONFLICT (conversation_id) DO UPDATE SET
                extracted_data = EXCLUDED.extracted_data,
                pending_confirmation = EXCLUDED.pending_confirmation,
                last_intent = EXCLUDED.last_intent,
                stage_entered_at = EXCLUDED.stage_entered_at,
                followups_sent_count = EXCLUDED.followups_sent_count,
                total_cost_usd = EXCLUDED.total_cost_usd,
                bot_paused = EXCLUDED.bot_paused,
                updated_at = now()
            """
        ),
        {
            "conversation_id": conv_id,
            "extracted": dumps(extracted),
            "pending_confirmation": "fecha_cita_objetivo"
            if lead["should_appoint"] and lead["stage"] != "cita_agendada"
            else None,
            "intent": lead["last_intent"],
            "stage_entered_at": last_activity_at - timedelta(hours=1 + lead["index"] % 8),
            "followups_sent": lead["index"] % 3,
            "cost": Decimal("0.004") + Decimal(lead["index"]) / Decimal("100000"),
            "bot_paused": lead["bot_paused"],
        },
    )

    message_ids: list[UUID] = []
    messages = [
        ("inbound", f"Hola, me interesa {lead['model_name']} en {lead['color']}.", 120),
        (
            "outbound",
            f"Hola {lead['name'].split()[0]}, claro. Tengo informacion publicada de {lead['model_name']}.",
            116,
        ),
        ("inbound", f"Quiero revisar {lead['plan']} y saber cuanto seria el enganche.", 95),
        (
            "outbound",
            f"Con {lead['plan']} puedo darte un estimado; el asesor confirma montos finales. Precio publicado: {money(lead['price'])}.",
            88,
        ),
        ("system", f"[mock-full] Stage set to {lead['stage']}.", 70),
        (
            "inbound",
            f"Mi ciudad es {lead['city']} y prefiero contacto por {lead['preference']}.",
            52,
        ),
        ("outbound", f"Perfecto. El siguiente paso es {next_action.replace('_', ' ')}.", 45),
    ]
    if lead["has_handoff"]:
        messages.append(("inbound", "Quiero que me atienda una persona, por favor.", 20))
    if lead["should_appoint"]:
        messages.append(
            ("outbound", "Puedo ayudarte a dejar una cita tentativa y el asesor la confirma.", 12)
        )
    for msg_idx, (direction, body, minutes_ago) in enumerate(messages, start=1):
        msg_id = await scalar_one(
            conn,
            """
            INSERT INTO messages (
                conversation_id, tenant_id, direction, text, channel_message_id, delivery_status,
                metadata_json, sent_at
            )
            VALUES (
                :conversation_id, :tenant_id, :direction, :body, :channel_message_id, :status,
                CAST(:metadata AS jsonb), :sent_at
            )
            RETURNING id
            """,
            {
                "conversation_id": conv_id,
                "tenant_id": tenant_id,
                "direction": direction,
                "body": body,
                "channel_message_id": f"mock-full:{lead['slug']}:{msg_idx}",
                "status": "read" if direction == "outbound" else "received",
                "metadata": dumps(
                    {
                        "mock_seed": MOCK_SEED,
                        "intent": lead["last_intent"],
                        "stage": lead["stage"],
                        "message_index": msg_idx,
                    }
                ),
                "sent_at": last_activity_at - timedelta(minutes=max(0, minutes_ago - 120)),
            },
        )
        message_ids.append(msg_id)

    await seed_traces_for_conversation(conn, tenant_id, conv_id, message_ids, lead)
    await seed_events_for_conversation(conn, tenant_id, user_ids, conv_id, lead, last_activity_at)
    await seed_handoff_followup_outbox(
        conn, tenant_id, user_ids, conv_id, message_ids, lead, assigned_user_id, last_activity_at
    )
    return customer_id, conv_id, message_ids


async def seed_traces_for_conversation(
    conn: AsyncConnection,
    tenant_id: UUID,
    conv_id: UUID,
    message_ids: list[UUID],
    lead: dict[str, Any],
) -> None:
    for turn_idx in range(1, 4):
        trace_id = await scalar_one(
            conn,
            """
            INSERT INTO turn_traces (
                conversation_id, tenant_id, turn_number, inbound_message_id, inbound_text,
                nlu_input, nlu_output, nlu_model, nlu_tokens_in, nlu_tokens_out, nlu_cost_usd, nlu_latency_ms,
                state_before, state_after, stage_transition, composer_input, composer_output, composer_model,
                composer_tokens_in, composer_tokens_out, composer_cost_usd, composer_latency_ms, tool_cost_usd,
                flow_mode, vision_cost_usd, vision_latency_ms, outbound_messages, total_cost_usd,
                total_latency_ms, errors, bot_paused, created_at
            )
            VALUES (
                :conversation_id, :tenant_id, :turn_number, :inbound_message_id, :inbound_text,
                CAST(:nlu_input AS jsonb), CAST(:nlu_output AS jsonb), :nlu_model, :nlu_tokens_in, :nlu_tokens_out, :nlu_cost, :nlu_latency,
                CAST(:state_before AS jsonb), CAST(:state_after AS jsonb), :stage_transition, CAST(:composer_input AS jsonb), CAST(:composer_output AS jsonb), :composer_model,
                :composer_tokens_in, :composer_tokens_out, :composer_cost, :composer_latency, :tool_cost,
                :flow_mode, :vision_cost, :vision_latency, CAST(:outbound_messages AS jsonb), :total_cost,
                :total_latency, CAST(:errors AS jsonb), :bot_paused, :created_at
            )
            RETURNING id
            """,
            {
                "conversation_id": conv_id,
                "tenant_id": tenant_id,
                "turn_number": turn_idx,
                "inbound_message_id": message_ids[min(turn_idx * 2 - 2, len(message_ids) - 1)],
                "inbound_text": f"Mock turn {turn_idx}: {lead['last_intent']}",
                "nlu_input": dumps({"text": "mock inbound", "stage": lead["stage"]}),
                "nlu_output": dumps(
                    {
                        "intent": lead["last_intent"],
                        "confidence": round(0.72 + turn_idx * 0.05, 2),
                        "entities": {"modelo_interes": lead["model_name"]},
                    }
                ),
                "nlu_model": "keyword-mock",
                "nlu_tokens_in": 90 + turn_idx * 13,
                "nlu_tokens_out": 28 + turn_idx * 4,
                "nlu_cost": Decimal("0.00040") + Decimal(turn_idx) / Decimal("100000"),
                "nlu_latency": 110 + turn_idx * 18,
                "state_before": dumps({"stage": STAGES[max(0, STAGES.index(lead["stage"]) - 1)]}),
                "state_after": dumps({"stage": lead["stage"], "mock_seed": MOCK_SEED}),
                "stage_transition": f"{STAGES[max(0, STAGES.index(lead['stage']) - 1)]}->{lead['stage']}"
                if turn_idx == 2
                else None,
                "composer_input": dumps(
                    {
                        "flow_mode": "SALES"
                        if lead["stage"] in {"propuesta", "negociacion", "cita_agendada"}
                        else "PLAN"
                    }
                ),
                "composer_output": dumps(
                    {"text": "Respuesta mock con fuentes y guardrails.", "confidence": 0.83}
                ),
                "composer_model": "canned-mock",
                "composer_tokens_in": 180 + turn_idx * 21,
                "composer_tokens_out": 54 + turn_idx * 9,
                "composer_cost": Decimal("0.00090") + Decimal(turn_idx) / Decimal("100000"),
                "composer_latency": 170 + turn_idx * 31,
                "tool_cost": Decimal("0.00020"),
                "flow_mode": "DOC"
                if lead["stage"] in {"documentacion", "validacion"}
                else (
                    "SALES"
                    if lead["stage"] in {"propuesta", "negociacion", "cita_agendada"}
                    else "PLAN"
                ),
                "vision_cost": Decimal("0.00000")
                if lead["docs_status"] == "missing"
                else Decimal("0.00050"),
                "vision_latency": None if lead["docs_status"] == "missing" else 220,
                "outbound_messages": dumps([{"text": "mock outbound", "status": "queued"}]),
                "total_cost": Decimal("0.00190") + Decimal(turn_idx) / Decimal("10000"),
                "total_latency": 420 + turn_idx * 55,
                "errors": dumps(
                    []
                    if lead["risk"] != "critical"
                    else [{"code": "LOW_CONFIDENCE", "message": "Mock critical risk"}]
                ),
                "bot_paused": lead["bot_paused"],
                "created_at": dt(minutes=-(lead["minutes_ago"] + 6 - turn_idx)),
            },
        )
        for tool_idx, tool_name in enumerate(
            ["lookup_faq", "search_catalog"]
            if turn_idx != 3
            else ["book_appointment" if lead["should_appoint"] else "escalate"]
        ):
            await conn.execute(
                text(
                    """
                    INSERT INTO tool_calls (turn_trace_id, tool_name, "input", "output", latency_ms, error, called_at)
                    VALUES (:turn_trace_id, :tool_name, CAST(:input_payload AS jsonb), CAST(:output_payload AS jsonb), :latency, :error, :called_at)
                    """
                ),
                {
                    "turn_trace_id": trace_id,
                    "tool_name": tool_name,
                    "input_payload": dumps(
                        {"mock_seed": MOCK_SEED, "lead": lead["slug"], "model": lead["model_name"]}
                    ),
                    "output_payload": dumps(
                        {"ok": True, "source": "mock", "score": 0.81 + tool_idx * 0.05}
                    ),
                    "latency": 95 + tool_idx * 45 + turn_idx * 15,
                    "error": None,
                    "called_at": dt(minutes=-(lead["minutes_ago"] + 4 - turn_idx)),
                },
            )


async def seed_events_for_conversation(
    conn: AsyncConnection,
    tenant_id: UUID,
    user_ids: dict[str, UUID],
    conv_id: UUID,
    lead: dict[str, Any],
    last_activity_at: datetime,
) -> None:
    events = [
        ("conversation.created", {"label": "Lead mock creado"}),
        ("message.received", {"label": "Inbound recibido", "intent": lead["last_intent"]}),
        ("ai.intent.detected", {"intent": lead["last_intent"], "confidence": 0.84}),
        (
            "conversation.stage.updated",
            {
                "stage": lead["stage"],
                "previous_stage": STAGES[max(0, STAGES.index(lead["stage"]) - 1)],
            },
        ),
        ("customer.score.updated", {"score": lead["score"], "risk": lead["risk"]}),
        (
            "workflow.evaluated",
            {"workflow": "[Mock] Reactivacion inteligente", "result": "matched"},
        ),
    ]
    for idx, (event_type, payload) in enumerate(events):
        payload = {"mock_seed": MOCK_SEED, "lead": lead["slug"], **payload}
        await conn.execute(
            text(
                """
                INSERT INTO events (
                    id, conversation_id, tenant_id, type, payload, occurred_at, trace_id, actor_user_id
                )
                VALUES (gen_random_uuid(), :conversation_id, :tenant_id, :type, CAST(:payload AS jsonb), :occurred_at, :trace_id, :actor_id)
                """
            ),
            {
                "conversation_id": conv_id,
                "tenant_id": tenant_id,
                "type": event_type,
                "payload": dumps(payload),
                "occurred_at": last_activity_at - timedelta(minutes=55 - idx * 8),
                "trace_id": f"mock-full-{lead['slug']}-{idx}",
                "actor_id": user_ids.get(lead["assigned_email"])
                if idx == 3 and lead["assigned_email"]
                else None,
            },
        )


async def seed_handoff_followup_outbox(
    conn: AsyncConnection,
    tenant_id: UUID,
    user_ids: dict[str, UUID],
    conv_id: UUID,
    message_ids: list[UUID],
    lead: dict[str, Any],
    assigned_user_id: UUID | None,
    last_activity_at: datetime,
) -> None:
    if lead["has_handoff"]:
        status = ["open", "assigned", "resolved"][lead["index"] % 3]
        await conn.execute(
            text(
                """
                INSERT INTO human_handoffs (
                    tenant_id, conversation_id, reason, payload, assigned_user_id, status, requested_at, resolved_at
                )
                VALUES (
                    :tenant_id, :conversation_id, :reason, CAST(:payload AS jsonb), :assigned_user_id, :status, :requested_at, :resolved_at
                )
                """
            ),
            {
                "tenant_id": tenant_id,
                "conversation_id": conv_id,
                "reason": f"MOCK-FULL: {lead['risk']} risk or human request in {lead['stage']}",
                "payload": dumps(
                    {
                        "mock_seed": MOCK_SEED,
                        "summary": f"{lead['name']} pide apoyo humano sobre {lead['model_name']}.",
                        "last_inbound_text": "Quiero hablar con una persona.",
                        "suggested_next_action": "Tomar control y confirmar siguiente paso.",
                        "priority": lead["risk"],
                        "sla_minutes": 15 if lead["risk"] == "critical" else 45,
                    }
                ),
                "assigned_user_id": assigned_user_id or user_ids["paola.soto@demo.com"],
                "status": status,
                "requested_at": last_activity_at - timedelta(minutes=18),
                "resolved_at": last_activity_at if status == "resolved" else None,
            },
        )
    if lead["has_followup"]:
        await conn.execute(
            text(
                """
                INSERT INTO followups_scheduled (
                    conversation_id, tenant_id, run_at, status, attempts, last_error, kind,
                    enqueued_at, cancelled_at, context
                )
                VALUES (
                    :conversation_id, :tenant_id, :run_at, :status, :attempts, :last_error, :kind,
                    :enqueued_at, :cancelled_at, CAST(:context AS jsonb)
                )
                """
            ),
            {
                "conversation_id": conv_id,
                "tenant_id": tenant_id,
                "run_at": dt(hours=lead["index"] % 36 + 1),
                "status": ["pending", "sent", "cancelled"][lead["index"] % 3],
                "attempts": lead["index"] % 4,
                "last_error": "mock transient Meta error" if lead["index"] % 11 == 0 else None,
                "kind": ["docs_missing", "appointment_confirm", "reactivation"][lead["index"] % 3],
                "enqueued_at": last_activity_at if lead["index"] % 3 == 1 else None,
                "cancelled_at": last_activity_at if lead["index"] % 3 == 2 else None,
                "context": dumps(
                    {"mock_seed": MOCK_SEED, "lead": lead["slug"], "stage": lead["stage"]}
                ),
            },
        )
    if lead["index"] % 2 == 0:
        await conn.execute(
            text(
                """
                INSERT INTO outbound_outbox (
                    tenant_id, idempotency_key, payload, status, attempts, channel_message_id,
                    sent_message_id, last_error, available_at
                )
                VALUES (
                    :tenant_id, :key, CAST(:payload AS jsonb), :status, :attempts, :channel_message_id,
                    :sent_message_id, :last_error, :available_at
                )
                """
            ),
            {
                "tenant_id": tenant_id,
                "key": f"mock-full:{lead['slug']}:outbound",
                "payload": dumps(
                    {
                        "mock_seed": MOCK_SEED,
                        "to": lead["phone"],
                        "text": f"Seguimiento para {lead['model_name']}",
                    }
                ),
                "status": ["pending", "sent", "failed"][lead["index"] % 3],
                "attempts": lead["index"] % 4,
                "channel_message_id": f"wamid.mock.{lead['slug']}"
                if lead["index"] % 3 == 1
                else None,
                "sent_message_id": message_ids[-1] if lead["index"] % 3 == 1 else None,
                "last_error": "mock WhatsApp provider unavailable"
                if lead["index"] % 3 == 2
                else None,
                "available_at": dt(minutes=lead["index"] * 2),
            },
        )


async def seed_customer_ai_reviews(
    conn: AsyncConnection,
    tenant_id: UUID,
    customer_ids: list[UUID],
    conv_ids: list[UUID],
    leads: list[dict[str, Any]],
) -> None:
    for idx, (customer_id, conv_id, lead) in enumerate(
        zip(customer_ids, conv_ids, leads, strict=True), start=1
    ):
        if idx % 3 != 0 and lead["risk"] not in {"high", "critical"}:
            continue
        await conn.execute(
            text(
                """
                INSERT INTO customer_ai_review_items (
                    id, tenant_id, customer_id, conversation_id, issue_type, severity, title, description,
                    ai_summary, confidence, risky_output_flag, human_review_required, status,
                    feedback_status, created_at, resolved_at
                )
                VALUES (
                    gen_random_uuid(), :tenant_id, :customer_id, :conversation_id, :issue_type, :severity, :title, :description,
                    :ai_summary, :confidence, :risky, :human_required, :status,
                    :feedback_status, :created_at, :resolved_at
                )
                """
            ),
            {
                "tenant_id": tenant_id,
                "customer_id": customer_id,
                "conversation_id": conv_id,
                "issue_type": [
                    "low_confidence",
                    "price_risk",
                    "handoff_quality",
                    "document_review",
                ][idx % 4],
                "severity": lead["risk"] if lead["risk"] in {"high", "critical"} else "medium",
                "title": f"[mock-full] Revisar respuesta IA para {lead['name']}",
                "description": "Item mock para probar bandeja de revision IA y feedback.",
                "ai_summary": f"La IA respondio sobre {lead['model_name']} con confianza limitada.",
                "confidence": round(0.52 + (idx % 30) / 100, 2),
                "risky": lead["risk"] == "critical",
                "human_required": True,
                "status": "resolved" if idx % 5 == 0 else "open",
                "feedback_status": "accepted" if idx % 5 == 0 else None,
                "created_at": dt(minutes=-(idx * 17)),
                "resolved_at": dt(minutes=-(idx * 7)) if idx % 5 == 0 else None,
            },
        )


async def seed_appointments(
    conn: AsyncConnection,
    tenant_id: UUID,
    user_ids: dict[str, UUID],
    customer_ids: list[UUID],
    conv_ids: list[UUID],
    leads: list[dict[str, Any]],
) -> None:
    statuses = [
        "scheduled",
        "confirmed",
        "arrived",
        "completed",
        "cancelled",
        "no_show",
        "rescheduled",
    ]
    advisors = [
        ("adv-ana", "Ana Garcia"),
        ("adv-luis", "Luis Ramirez"),
        ("adv-carlos", "Carlos Vega"),
        ("adv-diego", "Diego Rios"),
        ("adv-paola", "Paola Soto"),
    ]
    selected = [idx for idx, lead in enumerate(leads) if lead["should_appoint"]]
    extra = [idx for idx in range(len(leads)) if idx not in selected][:8]
    for order, lead_idx in enumerate(selected + extra, start=1):
        lead = leads[lead_idx]
        customer_id = customer_ids[lead_idx]
        conv_id = conv_ids[lead_idx]
        status = statuses[order % len(statuses)]
        start = (NOW + timedelta(days=(order % 15) - 5)).replace(
            hour=9 + order % 9, minute=0 if order % 2 else 30, second=0, microsecond=0
        )
        advisor_id, advisor_name = advisors[order % len(advisors)]
        if order % 11 == 0:
            start = start.replace(hour=11, minute=0)
            advisor_id, advisor_name = advisors[0]
        await conn.execute(
            text(
                """
                INSERT INTO appointments (
                    tenant_id, customer_id, conversation_id, scheduled_at, ends_at, appointment_type,
                    service, status, timezone, source, advisor_id, advisor_name, vehicle_id, vehicle_label,
                    ai_confidence, risk_score, risk_level, risk_reasons, recommended_actions, credit_plan,
                    down_payment_amount, down_payment_confirmed, documents_complete, last_customer_reply_at,
                    confirmed_at, arrived_at, completed_at, cancelled_at, no_show_at, reminder_status,
                    reminder_last_sent_at, action_log, ops_config, notes, created_by_id, created_by_type
                )
                VALUES (
                    :tenant_id, :customer_id, :conversation_id, :scheduled_at, :ends_at, :appointment_type,
                    :service, :status, 'America/Mexico_City', :source, :advisor_id, :advisor_name, :vehicle_id, :vehicle_label,
                    :ai_confidence, :risk_score, :risk_level, CAST(:risk_reasons AS jsonb), CAST(:recommended_actions AS jsonb), :credit_plan,
                    :down_payment, :down_confirmed, :docs_complete, :last_reply,
                    :confirmed_at, :arrived_at, :completed_at, :cancelled_at, :no_show_at, :reminder_status,
                    :reminder_sent, CAST(:action_log AS jsonb), CAST(:ops_config AS jsonb), :notes, :created_by_id, :created_by_type
                )
                """
            ),
            {
                "tenant_id": tenant_id,
                "customer_id": customer_id,
                "conversation_id": conv_id,
                "scheduled_at": start,
                "ends_at": start + timedelta(minutes=60 if order % 3 else 90),
                "appointment_type": ["test_drive", "credit_review", "delivery", "follow_up"][
                    order % 4
                ],
                "service": f"[Mock] {lead['model_name']} - {['Prueba de manejo', 'Revision de credito', 'Entrega', 'Seguimiento'][order % 4]}",
                "status": status,
                "source": ["manual", "ai", "whatsapp", "workflow"][order % 4],
                "advisor_id": advisor_id,
                "advisor_name": advisor_name,
                "vehicle_id": lead["model_sku"],
                "vehicle_label": f"{lead['model_name']} {lead['color']}",
                "ai_confidence": round(0.62 + (order % 35) / 100, 2),
                "risk_score": 20 + (order * 7) % 80,
                "risk_level": lead["risk"],
                "risk_reasons": dumps(
                    [
                        lead["sla"],
                        lead["docs_status"],
                        "mock_conflict" if order % 11 == 0 else "no_conflict",
                    ]
                ),
                "recommended_actions": dumps(
                    ["confirmar_asistencia", "enviar_recordatorio", "preparar_unidad"]
                ),
                "credit_plan": lead["plan"],
                "down_payment": int(lead["price"] * (0.10 if lead["plan"] == "Plan 10%" else 0.15)),
                "down_confirmed": status in {"confirmed", "arrived", "completed"},
                "docs_complete": lead["docs_status"] == "complete",
                "last_reply": dt(minutes=-(order * 23)),
                "confirmed_at": start - timedelta(days=1)
                if status in {"confirmed", "arrived", "completed"}
                else None,
                "arrived_at": start + timedelta(minutes=5)
                if status in {"arrived", "completed"}
                else None,
                "completed_at": start + timedelta(minutes=72) if status == "completed" else None,
                "cancelled_at": start - timedelta(hours=3) if status == "cancelled" else None,
                "no_show_at": start + timedelta(minutes=20) if status == "no_show" else None,
                "reminder_status": ["pending", "sent", "failed", "cancelled"][order % 4],
                "reminder_sent": start - timedelta(hours=4) if order % 4 == 1 else None,
                "action_log": dumps(
                    [
                        {"at": dt(days=-1).isoformat(), "actor": "mock_seed", "action": "created"},
                        {
                            "at": dt(hours=-2).isoformat(),
                            "actor": advisor_name,
                            "action": "reviewed",
                        },
                    ]
                ),
                "ops_config": dumps(
                    {
                        "mock_seed": MOCK_SEED,
                        "conflict_slot": order % 11 == 0,
                        "branch": lead["city"],
                        "checklist": ["unidad", "asesor", "documentos"],
                    }
                ),
                "notes": f"[mock-full] Cita mock para probar status {status}, conflictos, acciones y recordatorios.",
                "created_by_id": user_ids["admin@demo.com"],
                "created_by_type": "ai" if order % 3 == 0 else "user",
            },
        )
    print(f"[OK] Appointments ready: {len(selected + extra)}")


def workflow_definition(idx: int, label: str) -> dict[str, Any]:
    nodes = [
        {
            "id": "trigger",
            "type": "trigger",
            "title": "Nuevo evento",
            "config": {"event": "message_received"},
        },
        {
            "id": "detect",
            "type": "detect_intent",
            "title": "Detectar intencion",
            "config": {"store_as": "intent"},
        },
        {
            "id": "condition",
            "type": "condition",
            "title": "Requiere humano?",
            "config": {"field": "extracted.requires_human", "operator": "equals", "value": True},
        },
        {
            "id": "handoff",
            "type": "escalate_manager",
            "title": "Escalar",
            "config": {"reason": "Mock risk"},
        },
        {
            "id": "message",
            "type": "template_message",
            "title": "Enviar plantilla",
            "config": {
                "template": "mock_recordatorio_cita",
                "text": "Hola {{nombre}}, te damos seguimiento.",
            },
        },
        {"id": "end", "type": "end", "title": "Final", "config": {}},
    ]
    edges = [
        {"from": "trigger", "to": "detect"},
        {"from": "detect", "to": "condition"},
        {"from": "condition", "to": "handoff", "label": "true"},
        {"from": "condition", "to": "message", "label": "false"},
        {"from": "handoff", "to": "end"},
        {"from": "message", "to": "end"},
    ]
    return {
        "nodes": nodes,
        "edges": edges,
        "ops": {
            "mock_seed": MOCK_SEED,
            "metrics": {
                "executions_today": 34 + idx * 21,
                "success_rate": 96 - idx * 4,
                "failure_rate": idx * 3,
                "avg_duration_seconds": 18 + idx * 7,
                "dropoff_rate": idx * 4,
                "leads_affected_today": 18 + idx * 13,
                "critical_failures_24h": 0 if idx < 4 else 2,
                "ai_low_confidence_events": idx + 2,
                "sparkline": [40 + ((idx + s) * 9) % 55 for s in range(7)],
            },
            "safety_rules": {
                "business_hours": True,
                "max_3_messages_24h": True,
                "dedupe_template": True,
                "stop_on_no": True,
                "stop_on_human": True,
                "stop_on_frustration": True,
                "pause_on_critical": True,
            },
            "variable_status": {"documentos_faltantes": "faltante" if idx % 4 == 0 else "ok"},
            "dependency_status": {
                "bienvenida_v3": "ok",
                "Ventas Monterrey": "warning" if idx % 3 == 0 else "ok",
            },
            "label": label,
        },
    }


async def seed_workflows(
    conn: AsyncConnection,
    tenant_id: UUID,
    user_ids: dict[str, UUID],
    customer_ids: list[UUID],
    conv_ids: list[UUID],
) -> None:
    templates = [
        (
            "mock_bienvenida_operativa",
            "marketing",
            "approved",
            "Hola {{nombre}}, soy el asistente de AtendIA Demo Motors. Te ayudo con {{modelo_interes}}.",
        ),
        (
            "mock_recordatorio_cita",
            "utility",
            "approved",
            "Hola {{nombre}}, te recordamos tu cita de {{servicio}} a las {{hora}}.",
        ),
        (
            "mock_docs_faltantes",
            "utility",
            "approved",
            "Para avanzar faltan {{documentos_faltantes}}. Los puedes enviar por este chat.",
        ),
        (
            "mock_reactivacion",
            "marketing",
            "paused",
            "Hola {{nombre}}, seguimos disponibles para ayudarte con tu cotizacion.",
        ),
        (
            "mock_no_show",
            "utility",
            "approved",
            "Vimos que no pudiste asistir. Te ayudo a reagendar.",
        ),
    ]
    for name, category, status, body in templates:
        await conn.execute(
            text(
                """
                INSERT INTO whatsapp_templates (tenant_id, name, category, status, language, body, variables)
                VALUES (:tenant_id, :name, :category, :status, 'es_MX', :body, CAST(:vars AS jsonb))
                ON CONFLICT (tenant_id, name) DO UPDATE SET category = EXCLUDED.category, status = EXCLUDED.status, body = EXCLUDED.body, variables = EXCLUDED.variables
                """
            ),
            {
                "tenant_id": tenant_id,
                "name": name,
                "category": category,
                "status": status,
                "body": body,
                "vars": dumps(
                    ["nombre", "modelo_interes", "servicio", "hora", "documentos_faltantes"]
                ),
            },
        )
    for name, role in [
        ("[Mock] Recepcionista IA", "reception"),
        ("[Mock] Sales Agent", "sales"),
        ("[Mock] Supervisor IA", "supervisor"),
    ]:
        await conn.execute(
            text(
                """
                INSERT INTO ai_agents (tenant_id, name, role, status, config)
                VALUES (:tenant_id, :name, :role, 'active', CAST(:config AS jsonb))
                ON CONFLICT (tenant_id, name) DO UPDATE SET role = EXCLUDED.role, status = EXCLUDED.status, config = EXCLUDED.config
                """
            ),
            {
                "tenant_id": tenant_id,
                "name": name,
                "role": role,
                "config": dumps({"mock_seed": MOCK_SEED, "max_parallel_sessions": 50}),
            },
        )
    for source_name, source_type in [
        ("[Mock] Catalogo publicado", "catalog"),
        ("[Mock] FAQ credito", "faq"),
        ("[Mock] Manual operativo", "document"),
    ]:
        await conn.execute(
            text(
                """
                INSERT INTO knowledge_base_sources (tenant_id, name, source_type, status, metadata_json)
                VALUES (:tenant_id, :name, :source_type, 'indexed', CAST(:metadata AS jsonb))
                """
            ),
            {
                "tenant_id": tenant_id,
                "name": source_name,
                "source_type": source_type,
                "metadata": dumps({"mock_seed": MOCK_SEED, "last_indexed": NOW.isoformat()}),
            },
        )
    await conn.execute(
        text(
            """
            INSERT INTO advisor_pools (tenant_id, name, strategy, advisor_ids, active)
            VALUES (:tenant_id, '[Mock] Ventas nacional', 'round_robin', CAST(:advisor_ids AS jsonb), true)
            """
        ),
        {
            "tenant_id": tenant_id,
            "advisor_ids": dumps([str(user_ids[email]) for email in ADVISOR_EMAILS]),
        },
    )
    await conn.execute(
        text(
            """
            INSERT INTO business_hours_rules (tenant_id, name, timezone, schedule, active)
            VALUES (:tenant_id, '[Mock] Horario comercial MX', 'America/Mexico_City', CAST(:schedule AS jsonb), true)
            """
        ),
        {
            "tenant_id": tenant_id,
            "schedule": dumps(
                {"mon_fri": ["09:00", "19:00"], "sat": ["10:00", "16:00"], "sun": []}
            ),
        },
    )

    workflow_specs = [
        (
            "[Mock] Calificacion de nuevo lead",
            "message_received",
            "Captura datos minimos y asigna asesor.",
        ),
        (
            "[Mock] Documentos faltantes",
            "field_updated",
            "Detecta documentos incompletos y programa seguimiento.",
        ),
        (
            "[Mock] Confirmacion de cita",
            "appointment_created",
            "Confirma y recuerda citas con riesgo.",
        ),
        ("[Mock] Reactivacion inteligente", "stage_changed", "Recupera leads estancados por SLA."),
        ("[Mock] Escalacion critica", "bot_paused", "Pausa bot y crea handoff para supervisor."),
        ("[Mock] Postventa no show", "stage_entered", "Reagenda clientes no show o cancela flujo."),
    ]
    for idx, (name, trigger, desc) in enumerate(workflow_specs, start=1):
        wf_id = await scalar_one(
            conn,
            """
            INSERT INTO workflows (tenant_id, name, description, trigger_type, trigger_config, definition, active, version)
            VALUES (:tenant_id, :name, :description, :trigger_type, CAST(:trigger_config AS jsonb), CAST(:definition AS jsonb), :active, :version)
            RETURNING id
            """,
            {
                "tenant_id": tenant_id,
                "name": name,
                "description": desc,
                "trigger_type": trigger,
                "trigger_config": dumps(
                    {"mock_seed": MOCK_SEED, "stage": STAGES[idx % len(STAGES)]}
                ),
                "definition": dumps(workflow_definition(idx, name)),
                "active": idx != 6,
                "version": idx + 2,
            },
        )
        for version in range(1, 4):
            await conn.execute(
                text(
                    """
                    INSERT INTO workflow_versions (workflow_id, version_number, status, definition, change_summary, editor_name, published_at)
                    VALUES (:workflow_id, :version_number, :status, CAST(:definition AS jsonb), :summary, :editor, :published_at)
                    """
                ),
                {
                    "workflow_id": wf_id,
                    "version_number": version,
                    "status": "published" if version == 3 else "archived",
                    "definition": dumps(workflow_definition(idx, name)),
                    "summary": f"[mock-full] Workflow version {version}",
                    "editor": "Admin Demo",
                    "published_at": dt(days=-(idx + version)),
                },
            )
        for var_name in [
            "nombre",
            "telefono",
            "plan_credito",
            "modelo_moto",
            "documentos_faltantes",
            "asesor_asignado",
            "lifecycle_stage",
        ]:
            await conn.execute(
                text(
                    """
                    INSERT INTO workflow_variables (workflow_id, name, created_in_node_id, used_in_nodes, last_value, status)
                    VALUES (:workflow_id, :name, 'trigger', CAST(:used AS jsonb), :last_value, :status)
                    ON CONFLICT (workflow_id, name) DO UPDATE SET used_in_nodes = EXCLUDED.used_in_nodes, last_value = EXCLUDED.last_value, status = EXCLUDED.status
                    """
                ),
                {
                    "workflow_id": wf_id,
                    "name": var_name,
                    "used": dumps(["message", "condition"]),
                    "last_value": f"mock_{var_name}",
                    "status": "faltante"
                    if var_name == "documentos_faltantes" and idx % 4 == 0
                    else "ok",
                },
            )
        for dep_type, dep_name, dep_status in [
            ("whatsapp_template", "mock_recordatorio_cita", "ok"),
            ("ai_agent", "[Mock] Sales Agent", "ok"),
            ("knowledge_base", "[Mock] Manual operativo", "ok"),
            ("advisor_pool", "[Mock] Ventas nacional", "warning" if idx % 3 == 0 else "ok"),
        ]:
            await conn.execute(
                text(
                    """
                    INSERT INTO workflow_dependencies (workflow_id, dependency_type, name, status, details)
                    VALUES (:workflow_id, :dependency_type, :name, :status, CAST(:details AS jsonb))
                    """
                ),
                {
                    "workflow_id": wf_id,
                    "dependency_type": dep_type,
                    "name": dep_name,
                    "status": dep_status,
                    "details": dumps({"mock_seed": MOCK_SEED, "checked_at": NOW.isoformat()}),
                },
            )
        for key, label in [
            ("mock_business_hours", "Respetar horario"),
            ("mock_dedupe_template", "No repetir plantilla"),
            ("mock_stop_on_human", "Parar si pide humano"),
        ]:
            await conn.execute(
                text(
                    """
                    INSERT INTO safety_rules (tenant_id, workflow_id, key, label, enabled, config)
                    VALUES (:tenant_id, :workflow_id, :key, :label, true, CAST(:config AS jsonb))
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "workflow_id": wf_id,
                    "key": key,
                    "label": label,
                    "config": dumps({"mock_seed": MOCK_SEED}),
                },
            )
        for exec_idx in range(4):
            customer_id = customer_ids[(idx * 3 + exec_idx) % len(customer_ids)]
            conv_id = conv_ids[(idx * 3 + exec_idx) % len(conv_ids)]
            status = ["completed", "running", "failed", "paused"][exec_idx % 4]
            started = dt(minutes=-(idx * 25 + exec_idx * 11))
            execution_id = await scalar_one(
                conn,
                """
                INSERT INTO workflow_executions (
                    workflow_id, conversation_id, customer_id, trigger_event_id, status, current_node_id,
                    started_at, finished_at, error, error_code, steps_completed
                )
                VALUES (
                    :workflow_id, :conversation_id, :customer_id, :trigger_event_id, :status, :current_node_id,
                    :started_at, :finished_at, :error, :error_code, :steps_completed
                )
                RETURNING id
                """,
                {
                    "workflow_id": wf_id,
                    "conversation_id": conv_id,
                    "customer_id": customer_id,
                    "trigger_event_id": uuid4(),
                    "status": status,
                    "current_node_id": "end" if status == "completed" else "condition",
                    "started_at": started,
                    "finished_at": started + timedelta(seconds=35 + exec_idx * 8)
                    if status in {"completed", "failed", "paused"}
                    else None,
                    "error": "mock dependency warning" if status == "failed" else None,
                    "error_code": "MOCK_DEPENDENCY" if status == "failed" else None,
                    "steps_completed": 3 + exec_idx,
                },
            )
            for step_idx, node_id in enumerate(
                ["trigger", "detect", "condition", "message", "end"]
            ):
                step_status = (
                    "completed"
                    if step_idx <= exec_idx + 1 and status != "failed"
                    else ("failed" if status == "failed" and step_idx == 2 else "pending")
                )
                await conn.execute(
                    text(
                        """
                        INSERT INTO workflow_execution_steps (
                            execution_id, node_id, node_title, position, status, input_payload,
                            output_payload, error, started_at, finished_at, duration_ms
                        )
                        VALUES (
                            :execution_id, :node_id, :title, :position, :status, CAST(:input_payload AS jsonb),
                            CAST(:output_payload AS jsonb), :error, :started_at, :finished_at, :duration_ms
                        )
                        """
                    ),
                    {
                        "execution_id": execution_id,
                        "node_id": node_id,
                        "title": node_id.title(),
                        "position": step_idx,
                        "status": step_status,
                        "input_payload": dumps({"mock_seed": MOCK_SEED, "node": node_id}),
                        "output_payload": dumps({"ok": step_status != "failed"}),
                        "error": "mock failed condition" if step_status == "failed" else None,
                        "started_at": started + timedelta(seconds=step_idx * 4),
                        "finished_at": started + timedelta(seconds=step_idx * 4 + 3)
                        if step_status in {"completed", "failed"}
                        else None,
                        "duration_ms": 300 + step_idx * 70,
                    },
                )
            await conn.execute(
                text(
                    """
                    INSERT INTO workflow_action_runs (execution_id, node_id, action_key)
                    VALUES (:execution_id, 'message', :action_key)
                    """
                ),
                {"execution_id": execution_id, "action_key": f"mock-full:{name}:{exec_idx}"},
            )
    print(f"[OK] Workflows ready: {len(workflow_specs)}")


async def seed_notifications(
    conn: AsyncConnection, tenant_id: UUID, user_ids: dict[str, UUID], conv_ids: list[UUID]
) -> None:
    users = list(user_ids.values())
    titles = [
        "Handoff critico asignado",
        "Cita por confirmar",
        "Conflicto de KB detectado",
        "Workflow fallo en dependencia",
        "Lead con SLA vencido",
        "Documento rechazado",
        "Nueva pregunta sin respuesta",
        "Outbox con reintento pendiente",
    ]
    for idx in range(28):
        await conn.execute(
            text(
                """
                INSERT INTO notifications (tenant_id, user_id, title, body, read, source_type, source_id, created_at)
                VALUES (:tenant_id, :user_id, :title, :body, :read, 'mock_full_demo', :source_id, :created_at)
                """
            ),
            {
                "tenant_id": tenant_id,
                "user_id": users[idx % len(users)],
                "title": f"[Mock] {titles[idx % len(titles)]}",
                "body": "Notificacion mock para validar contador, lectura y menu.",
                "read": idx % 4 == 0,
                "source_id": conv_ids[idx % len(conv_ids)],
                "created_at": dt(minutes=-(idx * 9)),
            },
        )
    print("[OK] Notifications ready: 28")


async def touch_redis_channel_status(tenant_id: UUID) -> None:
    settings = get_settings()
    try:
        from redis.asyncio import Redis

        client = Redis.from_url(settings.redis_url, decode_responses=True)
        await client.set(f"webhook:last_at:{tenant_id}", NOW.isoformat(), ex=60 * 60 * 24)
        await client.aclose()
        print("[OK] Redis channel status touched")
    except Exception as exc:  # pragma: no cover - local dependency optional
        print(f"[--] Redis channel status skipped: {exc}")


async def summarize(conn: AsyncConnection, tenant_id: UUID) -> dict[str, int]:
    queries = {
        "users": "SELECT count(*) FROM tenant_users WHERE tenant_id = :tenant_id",
        "agents": "SELECT count(*) FROM agents WHERE tenant_id = :tenant_id AND name LIKE '[Mock]%'",
        "customers": "SELECT count(*) FROM customers WHERE tenant_id = :tenant_id AND tags @> CAST(:tag AS jsonb)",
        "conversations": "SELECT count(*) FROM conversations WHERE tenant_id = :tenant_id AND tags @> CAST(:tag AS jsonb)",
        "messages": "SELECT count(*) FROM messages WHERE tenant_id = :tenant_id AND metadata_json->>'mock_seed' = :seed",
        "appointments": "SELECT count(*) FROM appointments WHERE tenant_id = :tenant_id AND notes LIKE '[mock-full]%'",
        "handoffs": "SELECT count(*) FROM human_handoffs WHERE tenant_id = :tenant_id AND reason LIKE 'MOCK-FULL:%'",
        "followups": "SELECT count(*) FROM followups_scheduled WHERE tenant_id = :tenant_id AND context->>'mock_seed' = :seed",
        "workflows": "SELECT count(*) FROM workflows WHERE tenant_id = :tenant_id AND name LIKE '[Mock]%'",
        "workflow_executions": "SELECT count(*) FROM workflow_executions we JOIN workflows w ON w.id = we.workflow_id WHERE w.tenant_id = :tenant_id AND w.name LIKE '[Mock]%'",
        "faqs": "SELECT count(*) FROM tenant_faqs WHERE tenant_id = :tenant_id AND tags @> CAST(:tag AS jsonb)",
        "catalog_items": "SELECT count(*) FROM tenant_catalogs WHERE tenant_id = :tenant_id AND tags @> CAST(:tag AS jsonb)",
        "knowledge_documents": "SELECT count(*) FROM knowledge_documents WHERE tenant_id = :tenant_id AND filename LIKE 'mock-full-%'",
        "knowledge_chunks": "SELECT count(*) FROM knowledge_chunks WHERE tenant_id = :tenant_id AND text LIKE '[mock-full]%'",
        "kb_conflicts": "SELECT count(*) FROM kb_conflicts WHERE tenant_id = :tenant_id AND title LIKE '[Mock]%'",
        "kb_unanswered": "SELECT count(*) FROM kb_unanswered_questions WHERE tenant_id = :tenant_id AND query_normalized LIKE 'mock-full:%'",
        "kb_tests": "SELECT count(*) FROM kb_test_cases WHERE tenant_id = :tenant_id AND name LIKE '[Mock]%'",
        "notifications": "SELECT count(*) FROM notifications WHERE tenant_id = :tenant_id AND source_type = 'mock_full_demo'",
        "outbox": "SELECT count(*) FROM outbound_outbox WHERE tenant_id = :tenant_id AND idempotency_key LIKE 'mock-full:%'",
        "turn_traces": "SELECT count(*) FROM turn_traces WHERE tenant_id = :tenant_id AND nlu_input->>'stage' IS NOT NULL",
    }
    result: dict[str, int] = {}
    for key, sql in queries.items():
        result[key] = int(
            await scalar(
                conn,
                sql,
                {"tenant_id": tenant_id, "tag": dumps([MOCK_TAG]), "seed": MOCK_SEED},
            )
            or 0
        )
    return result


async def seed() -> None:
    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    async with engine.begin() as conn:
        tenant_id = await ensure_tenant(conn)
        await cleanup_mock(conn, tenant_id)
        user_ids = await ensure_users(conn, tenant_id)
        await ensure_pipeline_branding_and_tools(conn, tenant_id, user_ids)
        field_ids = await ensure_field_definitions(conn, tenant_id)
        agent_ids = await ensure_agents(conn, tenant_id)

        collections = await seed_kb_collections(conn, tenant_id)
        faq_ids, catalog_ids = await seed_faqs_and_catalog(conn, tenant_id, user_ids, collections)
        doc_ids = await seed_knowledge_documents(conn, tenant_id, user_ids, collections)
        await seed_kb_ops(conn, tenant_id, user_ids, collections, faq_ids, catalog_ids, doc_ids)

        customer_ids: list[UUID] = []
        conv_ids: list[UUID] = []
        stage_counts: Counter[str] = Counter()
        for lead in LEADS:
            customer_id, conv_id, _message_ids = await seed_customer_and_conversation(
                conn,
                tenant_id,
                user_ids,
                field_ids,
                agent_ids,
                lead,
            )
            customer_ids.append(customer_id)
            conv_ids.append(conv_id)
            stage_counts[lead["stage"]] += 1
        await seed_customer_ai_reviews(conn, tenant_id, customer_ids, conv_ids, LEADS)
        await seed_appointments(conn, tenant_id, user_ids, customer_ids, conv_ids, LEADS)
        await seed_workflows(conn, tenant_id, user_ids, customer_ids, conv_ids)
        await seed_notifications(conn, tenant_id, user_ids, conv_ids)
        counts = await summarize(conn, tenant_id)

    await engine.dispose()
    await touch_redis_channel_status(tenant_id)

    print()
    print("Full mock seed ready")
    print(f"Tenant: {DEMO_TENANT_NAME} ({tenant_id})")
    print(f"Login tenant admin: admin@demo.com / {DEMO_PASSWORD}")
    print(f"Login superadmin: superadmin@demo.com / {DEMO_PASSWORD}")
    print("Stage distribution:")
    for stage in STAGES:
        print(f"  - {stage}: {stage_counts[stage]}")
    print("Counts:")
    for key in sorted(counts):
        print(f"  - {key}: {counts[key]}")


if __name__ == "__main__":
    asyncio.run(seed())
