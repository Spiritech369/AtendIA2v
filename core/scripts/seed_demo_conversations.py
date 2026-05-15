"""Seed persistent demo conversations for the operator inbox.

Run from ``core/``:

    uv run python scripts/seed_demo_conversations.py

The seed is idempotent. It creates/updates the ``demo`` tenant, demo users,
pipeline, custom fields, catalog rows, customers, conversations, messages,
notes, appointments, handoffs and event rows. Conversation rows are identified
by tags like ``demo:diego-lopez`` and refreshed instead of duplicated.
"""

# ruff: noqa: E501
from __future__ import annotations

import asyncio
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from atendia.api._auth_helpers import hash_password
from atendia.config import get_settings

DEMO_TENANT_NAME = "demo"
DEMO_PASSWORD = "admin123"

PIPELINE_DEFINITION = {
    "stages": [
        {
            "id": "nuevo_lead",
            "label": "Nuevo lead",
            "timeout_hours": 2,
            "color": "#22c55e",
            "icon": "inbox",
            "allowed_transitions": ["en_conversacion"],
        },
        {
            "id": "en_conversacion",
            "label": "En conversacion",
            "timeout_hours": 4,
            "color": "#3b82f6",
            "icon": "message_circle",
            "allowed_transitions": ["documentacion", "propuesta", "negociacion"],
        },
        {
            "id": "documentacion",
            "label": "Documentacion",
            "timeout_hours": 12,
            "color": "#8b5cf6",
            "icon": "file_text",
            "allowed_transitions": ["validacion", "en_conversacion"],
        },
        {
            "id": "validacion",
            "label": "Validacion",
            "timeout_hours": 24,
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
            "timeout_hours": 12,
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
    "docs_per_plan": {
        "48 meses + 15% enganche": [
            {"field_name": "docs_ine", "label": "INE"},
            {"field_name": "docs_ine_reverso", "label": "INE reverso"},
            {"field_name": "docs_comprobante", "label": "Comprobante de domicilio"},
        ],
        "PLAN 10%": [
            {"field_name": "docs_ine", "label": "INE"},
            {"field_name": "docs_comprobante", "label": "Comprobante de domicilio"},
            {"field_name": "docs_nomina", "label": "Recibos de nomina"},
        ],
        "default": [
            {"field_name": "docs_ine", "label": "INE"},
            {"field_name": "docs_comprobante", "label": "Comprobante de domicilio"},
        ],
    },
}

FIELD_DEFINITIONS = [
    ("tipo_credito", "Tipo de credito", "select", {"choices": ["Bancario", "Nomina", "Contado"]}),
    (
        "plan_credito",
        "Plan de credito",
        "select",
        {"choices": ["PLAN 10%", "48 meses + 15% enganche", "Contado"]},
    ),
    ("modelo_interes", "Modelo de interes", "text", None),
    ("ingreso_estimado", "Ingreso estimado", "number", None),
    ("antiguedad_laboral", "Antiguedad laboral", "text", None),
    ("ciudad", "Ciudad", "text", None),
    ("docs_ine", "INE", "checkbox", None),
    ("docs_ine_reverso", "INE reverso", "checkbox", None),
    ("docs_comprobante", "Comprobante de domicilio", "checkbox", None),
    ("docs_nomina", "Recibos de nomina", "checkbox", None),
]

USERS = [
    ("admin@demo.com", "manager"),
    ("ana.garcia@demo.com", "operator"),
    ("luis.ramirez@demo.com", "operator"),
    ("carlos.vega@demo.com", "operator"),
]

ADVISORS = {
    "ana.garcia@demo.com": "Ana Garcia",
    "luis.ramirez@demo.com": "Luis Ramirez",
    "carlos.vega@demo.com": "Carlos Vega",
}

CATALOG_ITEMS = [
    {
        "sku": "HRV-EXL-2025",
        "name": "HR-V EXL 2025",
        "category": "autos",
        "price_cents": 48_990_000,
        "attrs": {
            "version": "EXL transmision CVT",
            "motor": "1.5L",
            "color": "Plata Lunar",
            "precio": 489900,
            "stock": 3,
        },
        "payment_plans": [
            {"name": "48 meses + 15% enganche", "down_payment_percent": 15},
            {"name": "PLAN 10%", "down_payment_percent": 10},
        ],
    },
    {
        "sku": "CIVIC-TOURING-2025",
        "name": "Civic Touring 2025",
        "category": "autos",
        "price_cents": 61_990_000,
        "attrs": {"version": "Touring CVT", "motor": "2.0L", "precio": 619900, "stock": 2},
        "payment_plans": [{"name": "PLAN 10%", "down_payment_percent": 10}],
    },
    {
        "sku": "CRV-TURBO-2025",
        "name": "CR-V Turbo 2025",
        "category": "autos",
        "price_cents": 74_990_000,
        "attrs": {"version": "Turbo Plus", "motor": "1.5T", "precio": 749900, "stock": 1},
        "payment_plans": [{"name": "48 meses + 15% enganche", "down_payment_percent": 15}],
    },
]

DEMO_CONVERSATIONS: list[dict[str, Any]] = [
    {
        "slug": "diego-lopez",
        "name": "Diego Lopez",
        "phone": "+525512345678",
        "email": "diego.lopez@example.com",
        "score": 94,
        "stage": "propuesta",
        "status": "active",
        "assigned": "ana.garcia@demo.com",
        "agent": "Ana Garcia",
        "unread": 3,
        "last_minutes_ago": 8,
        "last_intent": "ASK_PRICE",
        "tags": ["demo", "leads", "cotizacion", "alta_prioridad"],
        "attrs": {
            "source": "Facebook Ads",
            "campaign": "HR-V EXL Mayo",
            "estimated_value": 489900,
            "tipo_credito": "Bancario",
            "plan_credito": "48 meses + 15% enganche",
            "modelo_interes": "HR-V EXL 2025",
            "ciudad": "CDMX",
        },
        "extracted": {
            "source": {"value": "Facebook Ads", "confidence": 0.99},
            "campaign": {"value": "HR-V EXL Mayo", "confidence": 0.92},
            "estimated_value": {"value": 489900, "confidence": 0.96},
            "tipo_credito": {"value": "Bancario", "confidence": 0.9},
            "plan_credito": {"value": "48 meses + 15% enganche", "confidence": 0.91},
            "modelo_interes": {"value": "HR-V EXL 2025", "confidence": 0.95},
            "ciudad": {"value": "CDMX", "confidence": 0.82},
            "docs_ine": True,
            "docs_ine_reverso": False,
            "docs_comprobante": False,
        },
        "field_values": {
            "tipo_credito": "Bancario",
            "plan_credito": "48 meses + 15% enganche",
            "modelo_interes": "HR-V EXL 2025",
            "ingreso_estimado": "52000",
            "antiguedad_laboral": "+3 anos",
            "ciudad": "CDMX",
            "docs_ine": "true",
            "docs_ine_reverso": "false",
            "docs_comprobante": "false",
        },
        "messages": [
            ("inbound", "Hola, buenas tardes", 22),
            ("inbound", "Me pueden compartir informacion de la HR-V EXL 2025 en plata?", 21),
            (
                "outbound",
                "Hola Diego. Con gusto te comparto la informacion de la HR-V EXL 2025.",
                19,
            ),
            (
                "outbound",
                "HR-V EXL 2025 en plata: transmision CVT, motor 1.5L, precio $489,900 MXN.",
                17,
            ),
            (
                "outbound",
                "Tambien te puedo compartir el plan de financiamiento a 48 meses con 15% de enganche.",
                15,
            ),
            ("inbound", "Perfecto, me interesa agendar una prueba de manejo.", 8),
        ],
        "note": "Lead caliente. Quiere prueba de manejo de HR-V EXL 2025; faltan comprobante e INE reverso.",
        "appointment": ("Prueba de manejo HR-V EXL 2025", 1, 18),
    },
    {
        "slug": "karla-mendez",
        "name": "Karla Mendez",
        "phone": "+525598765432",
        "email": "karla.mendez@example.com",
        "score": 74,
        "stage": "documentacion",
        "status": "active",
        "assigned": "luis.ramirez@demo.com",
        "agent": "Luis Ramirez",
        "unread": 1,
        "last_minutes_ago": 12,
        "last_intent": "DOC_REQUIREMENTS",
        "tags": ["demo", "documentos", "nomina", "riesgo_medio"],
        "attrs": {
            "source": "Meta Ads",
            "campaign": "Nomina NL",
            "estimated_value": 489900,
            "tipo_credito": "Nomina",
            "plan_credito": "PLAN 10%",
            "modelo_interes": "HR-V EXL 2025",
            "ciudad": "Nuevo Leon",
        },
        "extracted": {
            "source": {"value": "Meta Ads", "confidence": 0.95},
            "campaign": {"value": "Nomina NL", "confidence": 0.89},
            "estimated_value": {"value": 489900, "confidence": 0.8},
            "tipo_credito": {"value": "Nomina", "confidence": 0.88},
            "plan_credito": {"value": "PLAN 10%", "confidence": 0.9},
            "modelo_interes": {"value": "HR-V EXL 2025", "confidence": 0.86},
            "ciudad": {"value": "Nuevo Leon", "confidence": 0.8},
            "docs_ine": True,
            "docs_comprobante": False,
            "docs_nomina": True,
        },
        "field_values": {
            "tipo_credito": "Nomina",
            "plan_credito": "PLAN 10%",
            "modelo_interes": "HR-V EXL 2025",
            "ingreso_estimado": "38000",
            "antiguedad_laboral": "+2 anos",
            "ciudad": "Nuevo Leon",
            "docs_ine": "true",
            "docs_comprobante": "false",
            "docs_nomina": "true",
        },
        "messages": [
            ("inbound", "Hola, vi el anuncio del plan 10%. Me interesa la HR-V.", 43),
            (
                "outbound",
                "Claro Karla, para PLAN 10% necesitamos INE, comprobante y recibos de nomina.",
                39,
            ),
            (
                "inbound",
                "Ya tengo INE y recibos. El comprobante de domicilio lo puedo mandar mas tarde?",
                12,
            ),
        ],
        "note": "Falta comprobante de domicilio. Buen potencial si se solicita hoy por WhatsApp.",
    },
    {
        "slug": "mariana-perez",
        "name": "Mariana Perez",
        "phone": "+525544332211",
        "email": "mariana.perez@example.com",
        "score": 82,
        "stage": "en_conversacion",
        "status": "active",
        "assigned": None,
        "agent": None,
        "unread": 2,
        "last_minutes_ago": 5,
        "last_intent": "AVAILABILITY",
        "tags": ["demo", "sin_asignar", "disponibilidad"],
        "attrs": {
            "source": "WhatsApp Click to Chat",
            "campaign": "Inventario Mayo",
            "estimated_value": 619900,
            "tipo_credito": "Bancario",
            "plan_credito": "PLAN 10%",
            "modelo_interes": "Civic Touring 2025",
            "ciudad": "Guadalajara",
        },
        "extracted": {
            "source": {"value": "WhatsApp Click to Chat", "confidence": 0.99},
            "campaign": {"value": "Inventario Mayo", "confidence": 0.76},
            "estimated_value": {"value": 619900, "confidence": 0.82},
            "tipo_credito": {"value": "Bancario", "confidence": 0.72},
            "plan_credito": {"value": "PLAN 10%", "confidence": 0.7},
            "modelo_interes": {"value": "Civic Touring 2025", "confidence": 0.89},
            "ciudad": {"value": "Guadalajara", "confidence": 0.81},
            "docs_ine": False,
            "docs_comprobante": False,
            "docs_nomina": False,
        },
        "field_values": {
            "tipo_credito": "Bancario",
            "plan_credito": "PLAN 10%",
            "modelo_interes": "Civic Touring 2025",
            "ciudad": "Guadalajara",
            "docs_ine": "false",
            "docs_comprobante": "false",
            "docs_nomina": "false",
        },
        "messages": [
            ("inbound", "Buen dia, tienen Civic Touring disponible en blanco?", 18),
            ("outbound", "Hola Mariana, reviso inventario y te confirmo disponibilidad.", 15),
            ("inbound", "Gracias, si tienen me gustaria verlo esta semana.", 5),
        ],
        "note": "Sin asignar. Pregunta por disponibilidad y quiere visita esta semana.",
    },
    {
        "slug": "jose-hernandez",
        "name": "Jose Hernandez",
        "phone": "+525566677788",
        "email": "jose.hernandez@example.com",
        "score": 89,
        "stage": "validacion",
        "status": "active",
        "assigned": "ana.garcia@demo.com",
        "agent": "Ana Garcia",
        "unread": 2,
        "last_minutes_ago": 65,
        "last_intent": "TEST_DRIVE",
        "tags": ["demo", "handoff", "prueba_manejo"],
        "handoff": "Cliente pidio prueba de manejo fuera de horario y requiere confirmacion humana.",
        "attrs": {
            "source": "Facebook Ads",
            "campaign": "Test Drive Weekend",
            "estimated_value": 749900,
            "tipo_credito": "Contado",
            "plan_credito": "Contado",
            "modelo_interes": "CR-V Turbo 2025",
            "ciudad": "Queretaro",
        },
        "extracted": {
            "source": {"value": "Facebook Ads", "confidence": 0.91},
            "campaign": {"value": "Test Drive Weekend", "confidence": 0.8},
            "estimated_value": {"value": 749900, "confidence": 0.86},
            "tipo_credito": {"value": "Contado", "confidence": 0.77},
            "plan_credito": {"value": "Contado", "confidence": 0.77},
            "modelo_interes": {"value": "CR-V Turbo 2025", "confidence": 0.92},
            "ciudad": {"value": "Queretaro", "confidence": 0.8},
            "docs_ine": False,
            "docs_comprobante": False,
        },
        "field_values": {
            "tipo_credito": "Contado",
            "plan_credito": "Contado",
            "modelo_interes": "CR-V Turbo 2025",
            "ciudad": "Queretaro",
            "docs_ine": "false",
            "docs_comprobante": "false",
        },
        "messages": [
            ("inbound", "Puedo agendar una prueba de manejo para este sabado?", 80),
            ("outbound", "Tengo disponibilidad preliminar. Te confirmo horario con un asesor.", 76),
            ("inbound", "Me urge porque voy a comprar esta semana.", 65),
        ],
        "note": "Handoff abierto por urgencia de compra y agenda fuera de horario.",
    },
    {
        "slug": "sofia-aguilar",
        "name": "Sofia Aguilar",
        "phone": "+525588990011",
        "email": "sofia.aguilar@example.com",
        "score": 68,
        "stage": "negociacion",
        "status": "active",
        "assigned": "carlos.vega@demo.com",
        "agent": "Carlos Vega",
        "unread": 0,
        "last_minutes_ago": 180,
        "last_intent": "FOLLOW_UP",
        "tags": ["demo", "seguimiento", "stale"],
        "attrs": {
            "source": "Referido",
            "campaign": "Clientes Honda",
            "estimated_value": 489900,
            "tipo_credito": "Bancario",
            "plan_credito": "48 meses + 15% enganche",
            "modelo_interes": "HR-V EXL 2025",
            "ciudad": "Puebla",
        },
        "extracted": {
            "source": {"value": "Referido", "confidence": 0.88},
            "campaign": {"value": "Clientes Honda", "confidence": 0.72},
            "estimated_value": {"value": 489900, "confidence": 0.7},
            "tipo_credito": {"value": "Bancario", "confidence": 0.7},
            "plan_credito": {"value": "48 meses + 15% enganche", "confidence": 0.74},
            "modelo_interes": {"value": "HR-V EXL 2025", "confidence": 0.8},
            "ciudad": {"value": "Puebla", "confidence": 0.76},
            "docs_ine": True,
            "docs_ine_reverso": True,
            "docs_comprobante": True,
        },
        "field_values": {
            "tipo_credito": "Bancario",
            "plan_credito": "48 meses + 15% enganche",
            "modelo_interes": "HR-V EXL 2025",
            "ciudad": "Puebla",
            "docs_ine": "true",
            "docs_ine_reverso": "true",
            "docs_comprobante": "true",
        },
        "messages": [
            ("inbound", "Ya envie mis documentos. Quedo pendiente de la cotizacion final.", 260),
            ("outbound", "Gracias Sofia, estamos validando y te actualizamos hoy.", 245),
            (
                "outbound",
                "Sofia, ya tengo el plan actualizado. Me confirmas si lo revisamos por llamada?",
                180,
            ),
        ],
        "note": "Documentacion completa. Hace falta reactivar con llamada o cierre de cotizacion.",
    },
]


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


async def ensure_tenant(conn: AsyncConnection) -> Any:
    tenant_id = (
        await conn.execute(
            text("SELECT id FROM tenants WHERE name = :name"), {"name": DEMO_TENANT_NAME}
        )
    ).scalar()
    if tenant_id is None:
        tenant_id = (
            await conn.execute(
                text(
                    "INSERT INTO tenants (name, plan, status, config) "
                    "VALUES (:name, 'standard', 'active', :config) RETURNING id"
                ),
                {"name": DEMO_TENANT_NAME, "config": dumps({"demo": True})},
            )
        ).scalar_one()
        print(f"[OK] Created tenant {DEMO_TENANT_NAME} ({tenant_id})")
    else:
        print(f"[--] Tenant {DEMO_TENANT_NAME} exists ({tenant_id})")
    return tenant_id


async def ensure_users(conn: AsyncConnection, tenant_id: Any) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for email, role in USERS:
        user_id = (
            await conn.execute(
                text("SELECT id FROM tenant_users WHERE tenant_id = :tenant_id AND email = :email"),
                {"tenant_id": tenant_id, "email": email},
            )
        ).scalar()
        if user_id is None:
            user_id = (
                await conn.execute(
                    text(
                        "INSERT INTO tenant_users (tenant_id, email, role, password_hash) "
                        "VALUES (:tenant_id, :email, :role, :password_hash) RETURNING id"
                    ),
                    {
                        "tenant_id": tenant_id,
                        "email": email,
                        "role": role,
                        "password_hash": hash_password(DEMO_PASSWORD),
                    },
                )
            ).scalar_one()
            print(f"[OK] Created user {email}")
        result[email] = user_id
    return result


async def ensure_agents(conn: AsyncConnection, tenant_id: Any) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for email, name in ADVISORS.items():
        agent_id = (
            await conn.execute(
                text("SELECT id FROM agents WHERE tenant_id = :tenant_id AND name = :name LIMIT 1"),
                {"tenant_id": tenant_id, "name": name},
            )
        ).scalar()
        if agent_id is None:
            agent_id = (
                await conn.execute(
                    text(
                        "INSERT INTO agents "
                        "(tenant_id, name, role, goal, style, tone, is_default, active_intents) "
                        "VALUES (:tenant_id, :name, 'sales', :goal, :style, 'amigable', false, :intents) "
                        "RETURNING id"
                    ),
                    {
                        "tenant_id": tenant_id,
                        "name": name,
                        "goal": "Gestionar leads demo y cerrar citas comerciales.",
                        "style": "asesor comercial mexicano, claro y compacto",
                        "intents": dumps(["ASK_PRICE", "AVAILABILITY", "TEST_DRIVE", "FOLLOW_UP"]),
                    },
                )
            ).scalar_one()
            print(f"[OK] Created advisor agent {name}")
        result[email] = agent_id
    return result


async def ensure_pipeline(conn: AsyncConnection, tenant_id: Any) -> None:
    await conn.execute(
        text("UPDATE tenant_pipelines SET active = false WHERE tenant_id = :tenant_id"),
        {"tenant_id": tenant_id},
    )
    await conn.execute(
        text(
            "INSERT INTO tenant_pipelines (tenant_id, version, definition, active) "
            "VALUES (:tenant_id, 20260510, :definition, true) "
            "ON CONFLICT (tenant_id, version) DO UPDATE SET "
            "definition = EXCLUDED.definition, active = true"
        ),
        {"tenant_id": tenant_id, "definition": dumps(PIPELINE_DEFINITION)},
    )
    print("[OK] Demo pipeline active")


async def ensure_field_definitions(conn: AsyncConnection, tenant_id: Any) -> dict[str, Any]:
    ids: dict[str, Any] = {}
    for ordering, (key, label, field_type, options) in enumerate(FIELD_DEFINITIONS):
        field_id = (
            await conn.execute(
                text(
                    "INSERT INTO customer_field_definitions "
                    "(id, tenant_id, key, label, field_type, field_options, ordering) "
                    "VALUES (gen_random_uuid(), :tenant_id, :key, :label, :field_type, :options, :ordering) "
                    "ON CONFLICT (tenant_id, key) DO UPDATE SET "
                    "label = EXCLUDED.label, field_type = EXCLUDED.field_type, "
                    "field_options = EXCLUDED.field_options, ordering = EXCLUDED.ordering "
                    "RETURNING id"
                ),
                {
                    "tenant_id": tenant_id,
                    "key": key,
                    "label": label,
                    "field_type": field_type,
                    "options": dumps(options) if options is not None else None,
                    "ordering": ordering,
                },
            )
        ).scalar_one()
        ids[key] = field_id
    print("[OK] Custom field definitions ready")
    return ids


async def ensure_catalog(conn: AsyncConnection, tenant_id: Any) -> None:
    for item in CATALOG_ITEMS:
        await conn.execute(
            text(
                "INSERT INTO tenant_catalogs "
                "(tenant_id, sku, name, attrs, tags, category, price_cents, stock_status, payment_plans, status) "
                "VALUES (:tenant_id, :sku, :name, :attrs, :tags, :category, :price_cents, 'in_stock', :plans, 'published') "
                "ON CONFLICT (tenant_id, sku) DO UPDATE SET "
                "name = EXCLUDED.name, attrs = EXCLUDED.attrs, tags = EXCLUDED.tags, "
                "category = EXCLUDED.category, price_cents = EXCLUDED.price_cents, "
                "stock_status = EXCLUDED.stock_status, payment_plans = EXCLUDED.payment_plans, "
                "status = 'published', active = true"
            ),
            {
                "tenant_id": tenant_id,
                "sku": item["sku"],
                "name": item["name"],
                "attrs": dumps(item["attrs"]),
                "tags": dumps(["demo", "autos", item["sku"]]),
                "category": item["category"],
                "price_cents": item["price_cents"],
                "plans": dumps(item["payment_plans"]),
            },
        )
    print("[OK] Demo catalog ready")


async def upsert_customer(conn: AsyncConnection, tenant_id: Any, spec: dict[str, Any]) -> Any:
    attrs = {**spec["attrs"], "demo_seed": True, "demo_slug": spec["slug"]}
    customer_id = (
        await conn.execute(
            text(
                "INSERT INTO customers (tenant_id, phone_e164, name, email, score, attrs) "
                "VALUES (:tenant_id, :phone, :name, :email, :score, :attrs) "
                "ON CONFLICT (tenant_id, phone_e164) DO UPDATE SET "
                "name = EXCLUDED.name, email = EXCLUDED.email, score = EXCLUDED.score, attrs = EXCLUDED.attrs "
                "RETURNING id"
            ),
            {
                "tenant_id": tenant_id,
                "phone": spec["phone"],
                "name": spec["name"],
                "email": spec["email"],
                "score": spec["score"],
                "attrs": dumps(attrs),
            },
        )
    ).scalar_one()
    return customer_id


async def upsert_field_values(
    conn: AsyncConnection,
    customer_id: Any,
    field_ids: dict[str, Any],
    values: dict[str, str],
) -> None:
    for key, value in values.items():
        field_id = field_ids.get(key)
        if field_id is None:
            continue
        await conn.execute(
            text(
                "INSERT INTO customer_field_values (customer_id, field_definition_id, value) "
                "VALUES (:customer_id, :field_id, :value) "
                "ON CONFLICT (customer_id, field_definition_id) DO UPDATE SET "
                "value = EXCLUDED.value, updated_at = now()"
            ),
            {"customer_id": customer_id, "field_id": field_id, "value": value},
        )


async def upsert_conversation(
    conn: AsyncConnection,
    tenant_id: Any,
    customer_id: Any,
    user_ids: dict[str, Any],
    agent_ids: dict[str, Any],
    spec: dict[str, Any],
) -> Any:
    tag_key = f"demo:{spec['slug']}"
    tags = [tag_key, *spec["tags"]]
    last_activity_at = datetime.now(UTC) - timedelta(minutes=spec["last_minutes_ago"])
    assigned_email = spec.get("assigned")
    assigned_user_id = user_ids.get(assigned_email) if assigned_email else None
    assigned_agent_id = agent_ids.get(assigned_email) if assigned_email else None

    existing_id = (
        await conn.execute(
            text(
                "SELECT id FROM conversations "
                "WHERE tenant_id = :tenant_id AND customer_id = :customer_id "
                "AND tags @> CAST(:tag AS jsonb) AND deleted_at IS NULL "
                "ORDER BY created_at DESC LIMIT 1"
            ),
            {"tenant_id": tenant_id, "customer_id": customer_id, "tag": dumps([tag_key])},
        )
    ).scalar()

    if existing_id is None:
        conv_id = (
            await conn.execute(
                text(
                    "INSERT INTO conversations "
                    "(tenant_id, customer_id, channel, status, current_stage, last_activity_at, "
                    "assigned_user_id, assigned_agent_id, unread_count, tags) "
                    "VALUES (:tenant_id, :customer_id, 'whatsapp_meta', :status, :stage, :last_activity_at, "
                    ":assigned_user_id, :assigned_agent_id, :unread, :tags) "
                    "RETURNING id"
                ),
                {
                    "tenant_id": tenant_id,
                    "customer_id": customer_id,
                    "status": spec["status"],
                    "stage": spec["stage"],
                    "last_activity_at": last_activity_at,
                    "assigned_user_id": assigned_user_id,
                    "assigned_agent_id": assigned_agent_id,
                    "unread": spec["unread"],
                    "tags": dumps(tags),
                },
            )
        ).scalar_one()
    else:
        conv_id = existing_id
        await conn.execute(
            text(
                "UPDATE conversations SET status = :status, current_stage = :stage, "
                "last_activity_at = :last_activity_at, assigned_user_id = :assigned_user_id, "
                "assigned_agent_id = :assigned_agent_id, unread_count = :unread, tags = :tags "
                "WHERE id = :conv_id"
            ),
            {
                "conv_id": conv_id,
                "status": spec["status"],
                "stage": spec["stage"],
                "last_activity_at": last_activity_at,
                "assigned_user_id": assigned_user_id,
                "assigned_agent_id": assigned_agent_id,
                "unread": spec["unread"],
                "tags": dumps(tags),
            },
        )

    await conn.execute(
        text(
            "INSERT INTO conversation_state "
            "(conversation_id, extracted_data, pending_confirmation, last_intent, stage_entered_at, bot_paused) "
            "VALUES (:conv_id, :extracted, NULL, :last_intent, :stage_entered_at, false) "
            "ON CONFLICT (conversation_id) DO UPDATE SET "
            "extracted_data = EXCLUDED.extracted_data, last_intent = EXCLUDED.last_intent, "
            "stage_entered_at = EXCLUDED.stage_entered_at, bot_paused = false, updated_at = now()"
        ),
        {
            "conv_id": conv_id,
            "extracted": dumps(spec["extracted"]),
            "last_intent": spec["last_intent"],
            "stage_entered_at": last_activity_at - timedelta(minutes=30),
        },
    )

    await refresh_messages(conn, tenant_id, conv_id, spec)
    await refresh_notes(conn, tenant_id, customer_id, user_ids, spec)
    await refresh_events(conn, tenant_id, conv_id, spec, last_activity_at)
    await refresh_handoff(conn, tenant_id, conv_id, spec, assigned_user_id)
    await refresh_appointment(conn, tenant_id, customer_id, conv_id, user_ids, spec)
    return conv_id


async def refresh_messages(
    conn: AsyncConnection,
    tenant_id: Any,
    conv_id: Any,
    spec: dict[str, Any],
) -> None:
    await conn.execute(
        text("DELETE FROM messages WHERE conversation_id = :conv_id"), {"conv_id": conv_id}
    )
    for index, (direction, body, minutes_ago) in enumerate(spec["messages"], start=1):
        await conn.execute(
            text(
                "INSERT INTO messages "
                "(tenant_id, conversation_id, direction, text, channel_message_id, delivery_status, metadata_json, sent_at) "
                "VALUES (:tenant_id, :conv_id, :direction, :body, :channel_message_id, 'delivered', :metadata, :sent_at)"
            ),
            {
                "tenant_id": tenant_id,
                "conv_id": conv_id,
                "direction": direction,
                "body": body,
                "channel_message_id": f"demo:{spec['slug']}:{index}",
                "metadata": dumps({"demo_seed": True, "intent": spec["last_intent"]}),
                "sent_at": datetime.now(UTC) - timedelta(minutes=minutes_ago),
            },
        )


async def refresh_notes(
    conn: AsyncConnection,
    tenant_id: Any,
    customer_id: Any,
    user_ids: dict[str, Any],
    spec: dict[str, Any],
) -> None:
    await conn.execute(
        text(
            "DELETE FROM customer_notes "
            "WHERE customer_id = :customer_id AND source IN ('demo_seed', 'ai_summary')"
        ),
        {"customer_id": customer_id},
    )
    author_id = user_ids.get(spec.get("assigned")) or user_ids["admin@demo.com"]
    await conn.execute(
        text(
            "INSERT INTO customer_notes "
            "(id, customer_id, tenant_id, author_user_id, source, content, pinned) "
            "VALUES (gen_random_uuid(), :customer_id, :tenant_id, :author_id, 'demo_seed', :content, true)"
        ),
        {
            "customer_id": customer_id,
            "tenant_id": tenant_id,
            "author_id": author_id,
            "content": spec["note"],
        },
    )
    await conn.execute(
        text(
            "INSERT INTO customer_notes "
            "(id, customer_id, tenant_id, author_user_id, source, content, pinned) "
            "VALUES (gen_random_uuid(), :customer_id, :tenant_id, NULL, 'ai_summary', :content, false)"
        ),
        {
            "customer_id": customer_id,
            "tenant_id": tenant_id,
            "content": f"Resumen IA demo: {spec['name']} esta en etapa {spec['stage']} con intencion {spec['last_intent']}.",
        },
    )


async def refresh_events(
    conn: AsyncConnection,
    tenant_id: Any,
    conv_id: Any,
    spec: dict[str, Any],
    last_activity_at: datetime,
) -> None:
    await conn.execute(
        text(
            "DELETE FROM events WHERE conversation_id = :conv_id AND payload->>'demo_seed' = 'true'"
        ),
        {"conv_id": conv_id},
    )
    events = [
        (
            "conversation.created",
            "Conversacion demo iniciada",
            last_activity_at - timedelta(hours=2),
        ),
        (
            "ai.intent.detected",
            f"Intencion {spec['last_intent']} detectada",
            last_activity_at - timedelta(minutes=50),
        ),
        (
            "conversation.stage.updated",
            f"Etapa actual: {spec['stage']}",
            last_activity_at - timedelta(minutes=30),
        ),
        ("message.received", "Ultimo mensaje del cliente", last_activity_at),
    ]
    for event_type, label, occurred_at in events:
        await conn.execute(
            text(
                "INSERT INTO events (id, conversation_id, tenant_id, type, payload, occurred_at) "
                "VALUES (gen_random_uuid(), :conv_id, :tenant_id, :type, :payload, :occurred_at)"
            ),
            {
                "conv_id": conv_id,
                "tenant_id": tenant_id,
                "type": event_type,
                "payload": dumps({"demo_seed": True, "label": label, "customer": spec["name"]}),
                "occurred_at": occurred_at,
            },
        )


async def refresh_handoff(
    conn: AsyncConnection,
    tenant_id: Any,
    conv_id: Any,
    spec: dict[str, Any],
    assigned_user_id: Any,
) -> None:
    await conn.execute(
        text(
            "DELETE FROM human_handoffs WHERE conversation_id = :conv_id AND reason LIKE 'DEMO:%'"
        ),
        {"conv_id": conv_id},
    )
    if not spec.get("handoff"):
        return
    await conn.execute(
        text(
            "INSERT INTO human_handoffs "
            "(id, tenant_id, conversation_id, reason, status, assigned_user_id, payload) "
            "VALUES (gen_random_uuid(), :tenant_id, :conv_id, :reason, 'open', :assigned_user_id, :payload)"
        ),
        {
            "tenant_id": tenant_id,
            "conv_id": conv_id,
            "reason": f"DEMO: {spec['handoff']}",
            "assigned_user_id": assigned_user_id,
            "payload": dumps(
                {
                    "demo_seed": True,
                    "last_inbound_text": spec["messages"][-1][1],
                    "suggested_next_action": "Confirmar disponibilidad y tomar control humano.",
                }
            ),
        },
    )


async def refresh_appointment(
    conn: AsyncConnection,
    tenant_id: Any,
    customer_id: Any,
    conv_id: Any,
    user_ids: dict[str, Any],
    spec: dict[str, Any],
) -> None:
    await conn.execute(
        text("DELETE FROM appointments WHERE conversation_id = :conv_id AND service LIKE 'Demo:%'"),
        {"conv_id": conv_id},
    )
    if not spec.get("appointment"):
        return
    title, days_from_now, hour = spec["appointment"]
    scheduled_at = (datetime.now(UTC) + timedelta(days=days_from_now)).replace(
        hour=hour,
        minute=0,
        second=0,
        microsecond=0,
    )
    await conn.execute(
        text(
            "INSERT INTO appointments "
            "(id, tenant_id, customer_id, conversation_id, scheduled_at, service, status, created_by_id, created_by_type) "
            "VALUES (gen_random_uuid(), :tenant_id, :customer_id, :conv_id, :scheduled_at, :service, 'scheduled', :created_by_id, 'user')"
        ),
        {
            "tenant_id": tenant_id,
            "customer_id": customer_id,
            "conv_id": conv_id,
            "scheduled_at": scheduled_at,
            "service": f"Demo: {title}",
            "created_by_id": user_ids["admin@demo.com"],
        },
    )


async def seed() -> None:
    engine = create_async_engine(get_settings().database_url)
    async with engine.begin() as conn:
        tenant_id = await ensure_tenant(conn)
        user_ids = await ensure_users(conn, tenant_id)
        agent_ids = await ensure_agents(conn, tenant_id)
        await ensure_pipeline(conn, tenant_id)
        field_ids = await ensure_field_definitions(conn, tenant_id)
        await ensure_catalog(conn, tenant_id)

        for spec in DEMO_CONVERSATIONS:
            customer_id = await upsert_customer(conn, tenant_id, spec)
            await upsert_field_values(conn, customer_id, field_ids, spec["field_values"])
            conv_id = await upsert_conversation(
                conn, tenant_id, customer_id, user_ids, agent_ids, spec
            )
            print(f"[OK] Demo conversation {spec['name']} ({conv_id})")

        total = (
            await conn.execute(
                text(
                    "SELECT count(*) FROM conversations "
                    "WHERE tenant_id = :tenant_id AND tags @> CAST(:tag AS jsonb) AND deleted_at IS NULL"
                ),
                {"tenant_id": tenant_id, "tag": dumps(["demo"])},
            )
        ).scalar_one()

    await engine.dispose()
    print()
    print(f"Demo conversations ready: {total}")
    print(f"Login: admin@demo.com / {DEMO_PASSWORD}")


if __name__ == "__main__":
    asyncio.run(seed())
