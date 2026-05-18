"""Prepare the beta demo tenant used for browser validation.

Run from ``core/``:

    uv run python scripts/prepare_beta_tenant.py

Defaults target ``test@test.com`` / ``test123``. The script resets only the
target user's tenant and seeds a clean Dinamo motorcycle-credit workspace:
pipeline, default Agent IA rules, catalog, FAQs, branding, and WhatsApp
sandbox metadata.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from atendia.api._auth_helpers import hash_password
from atendia.config import get_settings
from atendia.contracts.flow_mode import FlowMode
from atendia.runner.composer_prompts import MODE_PROMPTS
from atendia.state_machine.motos_credito_pipeline import (
    MOTOS_CREDITO_AGENT_FLOW_MODE_RULES,
    MOTOS_CREDITO_PIPELINE_DEFINITION,
)

# The composer is now generic: per-mode guidance comes from the tenant's
# pipeline.mode_prompts (UPPERCASE FlowMode keys), else a neutral default.
# Seed the Dinamo demo with the moto playbook as DATA so a freshly
# prepared beta tenant behaves exactly like before — without depending on
# the backfill migration having run.
MOTOS_CREDITO_PIPELINE_WITH_PROMPTS = {
    **MOTOS_CREDITO_PIPELINE_DEFINITION,
    "mode_prompts": {fm.value: MODE_PROMPTS[fm] for fm in FlowMode},
    "mode_labels": {
        "PLAN": "Calificación de crédito",
        "SALES": "Cotización de moto",
        "DOC": "Papelería",
        "OBSTACLE": "Objeciones",
        "RETENTION": "Seguimiento",
        "SUPPORT": "Dudas generales",
    },
    "hidden_modes": [],
}

DEFAULT_EMAIL = "test@test.com"
DEFAULT_PASSWORD = "test123"
DEFAULT_TENANT_NAME = "Dinamo Beta Demo"


TENANT_CONFIG: dict[str, Any] = {
    "beta_demo": True,
    "meta": {
        "business_name": "Dinamo Motos NL Sandbox",
        "phone_number": "+52 81 0000 0000",
        "phone_number_id": "sandbox_dinamo_phone_id",
        "verify_token": "atendia-dinamo-beta",
    },
    "inbox_config": {
        "layout": {
            "three_pane": True,
            "rail_width": "expanded",
            "composer_density": "comfortable",
            "sticky_composer": True,
        },
        "filter_chips": [
            {"id": "unread", "label": "Sin leer", "visible": True, "order": 0},
            {"id": "mine", "label": "Mias", "visible": True, "order": 1},
            {"id": "unassigned", "label": "Sin asignar", "visible": True, "order": 2},
            {"id": "docs", "label": "Docs", "visible": True, "order": 3},
        ],
    },
}


BRANDING = {
    "bot_name": "Dinamo",
    "voice": {
        "tone": "amigable",
        "style": "claro, breve, comercial sin prometer aprobaciones",
        "language": "es-MX",
    },
    "default_messages": {
        "brand_facts": {
            "brand": "Dinamo Motos NL",
            "catalog_url": "https://dinamomotos.com/catalogo.html",
            "credit_positioning": "Financiamiento propio para motos de trabajo y uso diario.",
            "safety": "No prometer aprobaciones, tasas finales ni inventario sin fuente publicada.",
            "handoff": "Cuando el expediente queda completo, pausar bot y pedir revision humana.",
        }
    },
}


AGENT_SYSTEM_PROMPT = """Eres Dinamo, asesor IA de Dinamo Motos NL.
Ayudas a elegir moto y ordenar el credito sin prometer aprobaciones.
Primero detecta uso, modelo de interes, ciudad y presupuesto. Si el cliente
quiere credito, identifica tipo de comprobacion y plan_credito antes de pedir
documentos. Si faltan datos, pregunta una sola cosa por turno. Si el expediente
queda completo o hay duda de aprobacion, pasa a revision humana."""


AGENT_KNOWLEDGE_CONFIG = {
    "linked_sources": ["catalog", "faq"],
    "collection_ids": [],
    "selected_tools": ["lookup_faq", "search_catalog", "lookup_requirements"],
}


CATALOG_ITEMS: list[dict[str, Any]] = [
    {
        "sku": "DINM-U5-2024",
        "name": "Dinamo U5",
        "category": "trabajo",
        "price_cents": 2899000,
        "stock_status": "in_stock",
        "attrs": {
            "motor": "150 cc",
            "uso_recomendado": "reparto urbano y trabajo diario",
            "enganche_desde": "10% con nomina por tarjeta",
        },
        "payment_plans": [
            {"id": "nomina_tarjeta_10", "label": "Nomina tarjeta 10% enganche"},
            {"id": "sin_comprobantes_25", "label": "Sin comprobantes 25% enganche"},
        ],
    },
    {
        "sku": "DINM-RX150-2024",
        "name": "Dinamo RX150",
        "category": "urbana",
        "price_cents": 3299000,
        "stock_status": "limited",
        "attrs": {
            "motor": "150 cc",
            "uso_recomendado": "ciudad, primer moto y traslados diarios",
            "enganche_desde": "15% con negocio/SAT",
        },
        "payment_plans": [
            {"id": "negocio_sat_15", "label": "Negocio/SAT 15% enganche"},
            {"id": "nomina_efectivo_20", "label": "Nomina efectivo 20% enganche"},
        ],
    },
    {
        "sku": "DINM-ADVENTURE-2024",
        "name": "Dinamo Adventure",
        "category": "doble_proposito",
        "price_cents": 4199000,
        "stock_status": "in_stock",
        "attrs": {
            "motor": "200 cc",
            "uso_recomendado": "rutas mixtas y trabajo con carga ligera",
            "enganche_desde": "20% con recibos de nomina",
        },
        "payment_plans": [
            {"id": "nomina_efectivo_20", "label": "Nomina efectivo 20% enganche"},
            {"id": "pensionado_imss_15", "label": "Pensionado IMSS 15% enganche"},
        ],
    },
]


FAQS: list[dict[str, str]] = [
    {
        "question": "Que documentos pide el credito con nomina por tarjeta?",
        "answer": "INE frente y reverso, comprobante de domicilio y estados de cuenta donde se vean depositos de nomina.",
    },
    {
        "question": "Que plan aplica si no tengo comprobantes de ingresos?",
        "answer": "Puede revisarse el plan sin comprobantes con 25% de enganche. Un asesor debe validar condiciones finales.",
    },
    {
        "question": "Puedo mandar documentos por WhatsApp?",
        "answer": "Si. Pide fotos completas, legibles, sin reflejos y con las cuatro esquinas visibles.",
    },
    {
        "question": "Cuando se pasa a revision humana?",
        "answer": "Cuando el expediente del plan esta completo, cuando el cliente pide aprobacion final o cuando hay dudas de politica de credito.",
    },
    {
        "question": "Se puede prometer aprobacion por chat?",
        "answer": "No. El bot solo orienta y junta informacion; la aprobacion final la confirma un asesor.",
    },
]


RESET_TABLES = [
    "workflow_event_cursors",
    "workflows",
    "events",
    "notifications",
    "outbound_outbox",
    "followups_scheduled",
    "human_handoffs",
    "appointments",
    "field_suggestions",
    "customer_field_definitions",
    "customers",
    "kb_test_runs",
    "kb_test_cases",
    "kb_unanswered_questions",
    "kb_conflicts",
    "kb_versions",
    "kb_health_snapshots",
    "kb_source_priority_rules",
    "kb_agent_permissions",
    "kb_safe_answer_settings",
    "knowledge_chunks",
    "knowledge_documents",
    "knowledge_base_sources",
    "tenant_catalogs",
    "tenant_faqs",
    "kb_collections",
    "tenant_pipelines",
    "tenant_templates_meta",
    "tenant_tools_config",
    "whatsapp_templates",
    "tenant_baileys_config",
    "ai_agents",
    "advisor_pools",
    "advisors",
    "vehicles",
    "business_hours_rules",
    "safety_rules",
    "agents",
]


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


async def _get_or_create_tenant(
    conn: AsyncConnection, *, email: str, password: str, tenant_name: str
) -> tuple[str, str]:
    existing = (
        await conn.execute(
            text(
                "SELECT tu.id, tu.tenant_id "
                "FROM tenant_users tu WHERE lower(tu.email) = lower(:email) "
                "ORDER BY tu.created_at DESC LIMIT 1"
            ),
            {"email": email},
        )
    ).first()

    if existing is not None:
        user_id, tenant_id = existing
        await conn.execute(
            text(
                "UPDATE tenant_users "
                "SET role = 'tenant_admin', password_hash = :password_hash "
                "WHERE id = :user_id"
            ),
            {"user_id": user_id, "password_hash": hash_password(password)},
        )
        return str(tenant_id), str(user_id)

    tenant_id = (
        await conn.execute(
            text(
                "INSERT INTO tenants (name, is_demo, config, timezone) "
                "VALUES (:name, false, CAST(:config AS jsonb), 'America/Mexico_City') "
                "RETURNING id"
            ),
            {"name": tenant_name, "config": dumps(TENANT_CONFIG)},
        )
    ).scalar_one()
    user_id = (
        await conn.execute(
            text(
                "INSERT INTO tenant_users (tenant_id, email, role, password_hash) "
                "VALUES (:tenant_id, :email, 'tenant_admin', :password_hash) RETURNING id"
            ),
            {
                "tenant_id": tenant_id,
                "email": email,
                "password_hash": hash_password(password),
            },
        )
    ).scalar_one()
    return str(tenant_id), str(user_id)


async def _reset_tenant(conn: AsyncConnection, tenant_id: str) -> dict[str, int]:
    deleted: dict[str, int] = {}
    for table_name in RESET_TABLES:
        result = await conn.execute(
            text(f"DELETE FROM {table_name} WHERE tenant_id = :tenant_id"),
            {"tenant_id": tenant_id},
        )
        deleted[table_name] = int(result.rowcount or 0)
    return deleted


async def _configure_tenant(
    conn: AsyncConnection, *, tenant_id: str, tenant_name: str, user_id: str
) -> None:
    conflicting_name = (
        await conn.execute(
            text("SELECT id FROM tenants WHERE name = :name AND id <> :tenant_id"),
            {"name": tenant_name, "tenant_id": tenant_id},
        )
    ).scalar_one_or_none()
    safe_name = tenant_name if conflicting_name is None else f"{tenant_name} {tenant_id[:8]}"

    await conn.execute(
        text(
            "UPDATE tenants SET name = :name, is_demo = false, "
            "timezone = 'America/Mexico_City', meta_business_id = 'sandbox_dinamo_waba', "
            "config = CAST(:config AS jsonb) WHERE id = :tenant_id"
        ),
        {"tenant_id": tenant_id, "name": safe_name, "config": dumps(TENANT_CONFIG)},
    )
    await conn.execute(
        text(
            "INSERT INTO tenant_branding (tenant_id, bot_name, voice, default_messages) "
            "VALUES (:tenant_id, :bot_name, CAST(:voice AS jsonb), CAST(:messages AS jsonb)) "
            "ON CONFLICT (tenant_id) DO UPDATE SET "
            "bot_name = EXCLUDED.bot_name, voice = EXCLUDED.voice, "
            "default_messages = EXCLUDED.default_messages"
        ),
        {
            "tenant_id": tenant_id,
            "bot_name": BRANDING["bot_name"],
            "voice": dumps(BRANDING["voice"]),
            "messages": dumps(BRANDING["default_messages"]),
        },
    )
    await conn.execute(
        text(
            "INSERT INTO tenant_pipelines (tenant_id, version, definition, active) "
            "VALUES (:tenant_id, 1, CAST(:definition AS jsonb), true)"
        ),
        {"tenant_id": tenant_id, "definition": dumps(MOTOS_CREDITO_PIPELINE_WITH_PROMPTS)},
    )
    await conn.execute(
        text(
            "INSERT INTO agents ("
            "tenant_id, name, role, status, behavior_mode, version, goal, style, tone, "
            "language, max_sentences, no_emoji, return_to_flow, is_default, "
            "system_prompt, active_intents, extraction_config, auto_actions, "
            "knowledge_config, flow_mode_rules, ops_config"
            ") VALUES ("
            ":tenant_id, 'Dinamo Asesor IA', 'sales', 'production', 'normal', 'beta-1', "
            ":goal, :style, 'amigable', 'es-MX', 4, true, true, true, "
            ":system_prompt, CAST(:active_intents AS jsonb), CAST(:extraction_config AS jsonb), "
            "CAST(:auto_actions AS jsonb), CAST(:knowledge_config AS jsonb), "
            "CAST(:flow_mode_rules AS jsonb), CAST(:ops_config AS jsonb)"
            ")"
        ),
        {
            "tenant_id": tenant_id,
            "goal": "Calificar leads de moto credito, explicar planes y preparar expediente.",
            "style": "Breve, humano, sin prometer aprobacion ni inventario final.",
            "system_prompt": AGENT_SYSTEM_PROMPT,
            # Valid NLU intents (UPPERCASE) — must match NLU_INTENTS in
            # agents_routes.py or the agent can't be saved from the UI.
            # (These are NLU intents, NOT flow modes.)
            "active_intents": dumps(
                [
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
                ]
            ),
            "extraction_config": dumps(
                {
                    "fields": [
                        "modelo_moto",
                        "tipo_credito",
                        "plan_credito",
                        "antiguedad_laboral_meses",
                    ]
                }
            ),
            "auto_actions": dumps({"pause_on_docs_complete": True}),
            "knowledge_config": dumps(AGENT_KNOWLEDGE_CONFIG),
            "flow_mode_rules": dumps(MOTOS_CREDITO_AGENT_FLOW_MODE_RULES),
            "ops_config": dumps({"seeded_by": "prepare_beta_tenant", "owner_user_id": user_id}),
        },
    )


async def _seed_knowledge(conn: AsyncConnection, *, tenant_id: str, user_id: str) -> None:
    for item in CATALOG_ITEMS:
        await conn.execute(
            text(
                "INSERT INTO tenant_catalogs ("
                "tenant_id, sku, name, category, attrs, tags, active, status, visibility, "
                "priority, created_by, updated_by, agent_permissions, language, price_cents, "
                "stock_status, region, branch, payment_plans"
                ") VALUES ("
                ":tenant_id, :sku, :name, :category, CAST(:attrs AS jsonb), "
                "CAST(:tags AS jsonb), true, 'published', 'agents', :priority, "
                ":user_id, :user_id, CAST(:agent_permissions AS jsonb), 'es-MX', "
                ":price_cents, :stock_status, 'Nuevo Leon', 'Sandbox', "
                "CAST(:payment_plans AS jsonb)"
                ")"
            ),
            {
                "tenant_id": tenant_id,
                "sku": item["sku"],
                "name": item["name"],
                "category": item["category"],
                "attrs": dumps(item["attrs"]),
                "tags": dumps(["beta", "dinamo", "catalog"]),
                "priority": 20,
                "user_id": user_id,
                "agent_permissions": dumps(["Dinamo Asesor IA"]),
                "price_cents": item["price_cents"],
                "stock_status": item["stock_status"],
                "payment_plans": dumps(item["payment_plans"]),
            },
        )

    for index, faq in enumerate(FAQS):
        await conn.execute(
            text(
                "INSERT INTO tenant_faqs ("
                "tenant_id, question, answer, tags, status, visibility, priority, "
                "created_by, updated_by, agent_permissions, language"
                ") VALUES ("
                ":tenant_id, :question, :answer, CAST(:tags AS jsonb), 'published', "
                "'agents', :priority, :user_id, :user_id, CAST(:agent_permissions AS jsonb), 'es-MX'"
                ")"
            ),
            {
                "tenant_id": tenant_id,
                "question": faq["question"],
                "answer": faq["answer"],
                "tags": dumps(["beta", "dinamo", "faq"]),
                "priority": 15 - index,
                "user_id": user_id,
                "agent_permissions": dumps(["Dinamo Asesor IA"]),
            },
        )


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--email", default=DEFAULT_EMAIL)
    parser.add_argument("--password", default=DEFAULT_PASSWORD)
    parser.add_argument("--tenant-name", default=DEFAULT_TENANT_NAME)
    args = parser.parse_args()

    engine = create_async_engine(get_settings().database_url)
    try:
        async with engine.begin() as conn:
            tenant_id, user_id = await _get_or_create_tenant(
                conn, email=args.email, password=args.password, tenant_name=args.tenant_name
            )
            deleted = await _reset_tenant(conn, tenant_id)
            await _configure_tenant(
                conn, tenant_id=tenant_id, tenant_name=args.tenant_name, user_id=user_id
            )
            await _seed_knowledge(conn, tenant_id=tenant_id, user_id=user_id)

        print("Beta tenant prepared")
        print(f"  email:     {args.email}")
        print(f"  password:  {args.password}")
        print(f"  tenant_id: {tenant_id}")
        print(f"  user_id:   {user_id}")
        print("  reset rows:")
        for table_name, count in deleted.items():
            if count:
                print(f"    {table_name}: {count}")
        print("  seeded: pipeline=1 agents=1 catalog=3 faqs=5")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(130)
