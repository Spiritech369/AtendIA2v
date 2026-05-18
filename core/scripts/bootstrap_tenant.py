"""Bootstrap a clean tenant in one pass.

Run from ``core/``:

    uv run python scripts/bootstrap_tenant.py --email admin@demo.com --password admin123

The script seeds the core surfaces needed for a working sales tenant:
customer fields, pipeline, document catalog, docs-per-plan, Vision mapping,
composer mode prompts, Knowledge Base chunks, QoS and a default agent.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from atendia.api._auth_helpers import hash_password
from atendia.config import get_settings
from atendia.config_validation import validate_pipeline_config


DEFAULT_EMAIL = "admin@demo.com"
DEFAULT_PASSWORD = "admin123"
DEFAULT_TENANT_NAME = "AtendIA Tenant Core"

REPO_ROOT = Path(__file__).resolve().parents[2]


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


CUSTOMER_FIELDS: list[dict[str, Any]] = [
    {
        "key": "antiguedad",
        "label": "Antiguedad laboral",
        "field_type": "checkbox",
        "field_options": {"instructions": "true si tiene 6 meses o mas; false si no cumple."},
        "ordering": 10,
    },
    {
        "key": "tipo_credito",
        "label": "Tipo de credito",
        "field_type": "select",
        "field_options": {
            "choices": [
                "Nómina Tarjeta",
                "Nómina Recibos",
                "Pensionados",
                "Negocio SAT",
                "Sin Comprobantes",
                "Guardia de Seguridad",
            ],
            "instructions": "Guardar el nombre exacto del tipo de credito.",
        },
        "ordering": 20,
    },
    {
        "key": "credito_plan",
        "label": "Plan de credito",
        "field_type": "select",
        "field_options": {
            "choices": ["10%", "15%", "20%", "30%"],
            "instructions": "Guardar solo el porcentaje exacto.",
        },
        "ordering": 21,
    },
    {
        "key": "modelo_moto",
        "label": "Modelo moto",
        "field_type": "text",
        "field_options": {"instructions": "Nombre canonico del catalogo."},
        "ordering": 22,
    },
]

DOCUMENT_FIELDS: list[dict[str, Any]] = [
    ("DOCS_INE_FRENTE", "INE - Frente"),
    ("DOCS_INE_ATRAS", "INE - Reverso"),
    ("DOCS_DOMICILIO", "Comprobante de domicilio"),
    ("DOCS_ESTADOS_CUENTA", "Estados de cuenta"),
    ("DOCS_RECIBOS_NOMINA", "Recibos de nomina"),
    ("DOCS_CONSTANCIA_SAT", "Constancia SAT/RIF"),
    ("DOCS_FACTURA_INSUMO", "Factura de insumo"),
    ("DOCS_RESOLUCION_IMSS", "Resolucion IMSS"),
]

for order, (key, label) in enumerate(DOCUMENT_FIELDS, start=100):
    CUSTOMER_FIELDS.append(
        {
            "key": key,
            "label": label,
            "field_type": "select",
            "field_options": {"choices": ["missing", "ok", "rejected"], "is_document_status": True},
            "ordering": order,
        }
    )


DOCUMENTS_CATALOG = [
    {"key": key, "label": label, "hint": ""}
    for key, label in DOCUMENT_FIELDS
]

DOCS_PER_PLAN = {
    "Nómina Tarjeta": [
        "DOCS_INE_FRENTE",
        "DOCS_INE_ATRAS",
        "DOCS_DOMICILIO",
        "DOCS_ESTADOS_CUENTA",
    ],
    "Nómina Recibos": [
        "DOCS_INE_FRENTE",
        "DOCS_INE_ATRAS",
        "DOCS_DOMICILIO",
        "DOCS_RECIBOS_NOMINA",
    ],
    "Pensionados": [
        "DOCS_INE_FRENTE",
        "DOCS_INE_ATRAS",
        "DOCS_DOMICILIO",
        "DOCS_ESTADOS_CUENTA",
        "DOCS_RESOLUCION_IMSS",
    ],
    "Negocio SAT": [
        "DOCS_INE_FRENTE",
        "DOCS_INE_ATRAS",
        "DOCS_DOMICILIO",
        "DOCS_CONSTANCIA_SAT",
        "DOCS_FACTURA_INSUMO",
    ],
    "Sin Comprobantes": [
        "DOCS_INE_FRENTE",
        "DOCS_INE_ATRAS",
        "DOCS_DOMICILIO",
    ],
    "Guardia de Seguridad": [
        "DOCS_INE_FRENTE",
        "DOCS_INE_ATRAS",
        "DOCS_DOMICILIO",
        "DOCS_ESTADOS_CUENTA",
        "DOCS_RECIBOS_NOMINA",
    ],
}

VISION_DOC_MAPPING = {
    "ine": ["DOCS_INE_FRENTE", "DOCS_INE_ATRAS"],
    "comprobante": ["DOCS_DOMICILIO"],
    "estado_cuenta": ["DOCS_ESTADOS_CUENTA"],
    "recibo_nomina": ["DOCS_RECIBOS_NOMINA"],
    "constancia_sat": ["DOCS_CONSTANCIA_SAT"],
    "factura": ["DOCS_FACTURA_INSUMO"],
    "imss": ["DOCS_RESOLUCION_IMSS"],
}

MODE_PROMPTS = {
    "PLAN": (
        "Califica sin repetir pasos. Responde primero la pregunta o comentario del cliente "
        "y agrega solo el siguiente dato faltante. El estado es progresivo: si ya existe "
        "antiguedad, tipo_credito, credito_plan, modelo_moto o documentos, no los pidas otra vez."
    ),
    "SALES": (
        "Cotiza solo con evidencia recuperada del catalogo. No inventes precios, enganches, "
        "pagos, plazos ni disponibilidad. Si falta plan o modelo, pide solo ese dato."
    ),
    "DOC": (
        "Pide requisitos en una sola respuesta breve. Usa lista numerada corta. No dupliques "
        "documentos equivalentes: INE por ambos lados equivale a frente y reverso."
    ),
    "OBSTACLE": "Responde la objecion breve y vuelve al unico dato faltante para avanzar.",
    "RETENTION": "Da seguimiento corto, contextual y sin reiniciar el flujo.",
    "SUPPORT": "Responde dudas generales solo con evidencia de KB o escala si no hay evidencia.",
}

PIPELINE_DEFINITION = {
    "version": 1,
    "nlu": {"history_turns": 2},
    "composer": {"history_turns": 2},
    "fallback": "escalate_to_human",
    "docs_plan_field": "tipo_credito",
    "documents_catalog": DOCUMENTS_CATALOG,
    "docs_per_plan": DOCS_PER_PLAN,
    "vision_doc_mapping": VISION_DOC_MAPPING,
    "mode_prompts": MODE_PROMPTS,
    "stages": [
        {
            "id": "nuevo_lead",
            "label": "Nuevo lead",
            "actions_allowed": ["greet", "ask_field", "lookup_faq", "search_catalog"],
        },
        {
            "id": "calificacion",
            "label": "Calificacion",
            "actions_allowed": ["ask_field", "lookup_faq", "search_catalog"],
            "auto_enter_rules": {
                "enabled": True,
                "match": "all",
                "conditions": [{"field": "antiguedad", "operator": "exists"}],
            },
        },
        {
            "id": "cotizacion",
            "label": "Cotizacion",
            "actions_allowed": ["quote", "lookup_faq", "search_catalog"],
            "auto_enter_rules": {
                "enabled": True,
                "match": "all",
                "conditions": [
                    {"field": "tipo_credito", "operator": "exists"},
                    {"field": "credito_plan", "operator": "exists"},
                    {"field": "modelo_moto", "operator": "exists"},
                ],
            },
        },
        {
            "id": "papeleria_incompleta",
            "label": "Papeleria incompleta",
            "actions_allowed": ["ask_field", "lookup_faq", "escalate_to_human"],
        },
        {
            "id": "papeleria_completa",
            "label": "Papeleria completa",
            "actions_allowed": ["escalate_to_human"],
            "pause_bot_on_enter": True,
            "handoff_reason": "docs_complete_for_plan",
            "auto_enter_rules": {
                "enabled": True,
                "match": "all",
                "conditions": [{"field": "tipo_credito", "operator": "docs_complete_for_plan"}],
            },
        },
    ],
}

TENANT_CONFIG = {
    "qos": {
        "enabled": True,
        "response_slo_ms": 8000,
        "max_messages_per_turn": 1,
    }
}

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
    "knowledge_chunks",
    "knowledge_documents",
    "tenant_catalogs",
    "tenant_faqs",
    "kb_collections",
    "tenant_pipelines",
    "tenant_branding",
    "agents",
]


async def get_or_create_tenant(
    conn: AsyncConnection,
    *,
    email: str,
    password: str,
    tenant_name: str,
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
    if existing:
        user_id, tenant_id = existing
        await conn.execute(
            text(
                "UPDATE tenant_users SET role='tenant_admin', password_hash=:password_hash "
                "WHERE id=:user_id"
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
            {"tenant_id": tenant_id, "email": email, "password_hash": hash_password(password)},
        )
    ).scalar_one()
    return str(tenant_id), str(user_id)


async def reset_tenant(conn: AsyncConnection, tenant_id: str) -> dict[str, int]:
    deleted: dict[str, int] = {}
    for table_name in RESET_TABLES:
        result = await conn.execute(
            text(f"DELETE FROM {table_name} WHERE tenant_id = :tenant_id"),
            {"tenant_id": tenant_id},
        )
        deleted[table_name] = int(result.rowcount or 0)
    return deleted


async def seed_customer_fields(conn: AsyncConnection, tenant_id: str) -> None:
    for item in CUSTOMER_FIELDS:
        await conn.execute(
            text(
                "INSERT INTO customer_field_definitions "
                "(id, tenant_id, key, label, field_type, field_options, ordering) "
                "VALUES (gen_random_uuid(), :tenant_id, :key, :label, :field_type, "
                "CAST(:field_options AS jsonb), :ordering) "
                "ON CONFLICT (tenant_id, key) DO UPDATE SET "
                "label=EXCLUDED.label, field_type=EXCLUDED.field_type, "
                "field_options=EXCLUDED.field_options, ordering=EXCLUDED.ordering"
            ),
            {
                "tenant_id": tenant_id,
                "key": item["key"],
                "label": item["label"],
                "field_type": item["field_type"],
                "field_options": dumps(item.get("field_options") or {}),
                "ordering": item["ordering"],
            },
        )


async def seed_pipeline(conn: AsyncConnection, tenant_id: str) -> None:
    await conn.execute(text("DELETE FROM tenant_pipelines WHERE tenant_id=:tenant_id"), {"tenant_id": tenant_id})
    await conn.execute(
        text(
            "INSERT INTO tenant_pipelines (tenant_id, version, definition, active, history) "
            "VALUES (:tenant_id, 1, CAST(:definition AS jsonb), true, "
            "jsonb_build_array(jsonb_build_object('index', 1, 'definition', CAST(:definition AS jsonb))))"
        ),
        {"tenant_id": tenant_id, "definition": dumps(PIPELINE_DEFINITION)},
    )


def chunk_text(text_value: str, size: int = 12000) -> list[str]:
    return [text_value[i : i + size] for i in range(0, len(text_value), size)] or [text_value]


async def seed_kb_document(
    conn: AsyncConnection,
    *,
    tenant_id: str,
    user_id: str,
    filename: str,
    category: str,
    text_value: str,
) -> None:
    chunks = chunk_text(text_value)
    document_id = (
        await conn.execute(
            text(
                "INSERT INTO knowledge_documents "
                "(tenant_id, filename, storage_path, category, status, fragment_count, "
                "visibility, priority, created_by, updated_by, agent_permissions, progress_percentage, "
                "embedded_chunk_count, error_count) "
                "VALUES (:tenant_id, :filename, :storage_path, :category, 'indexed', :count, "
                "'agents', 50, :user_id, :user_id, CAST(:agent_permissions AS jsonb), 100, 0, 0) "
                "RETURNING id"
            ),
            {
                "tenant_id": tenant_id,
                "filename": filename,
                "storage_path": f"seed://{filename}",
                "category": category,
                "count": len(chunks),
                "user_id": user_id,
                "agent_permissions": dumps(["Core Sales Agent"]),
            },
        )
    ).scalar_one()
    for index, chunk in enumerate(chunks):
        await conn.execute(
            text(
                "INSERT INTO knowledge_chunks "
                "(document_id, tenant_id, chunk_index, text, chunk_status, token_count) "
                "VALUES (:document_id, :tenant_id, :chunk_index, :text, 'embedded', :token_count)"
            ),
            {
                "document_id": document_id,
                "tenant_id": tenant_id,
                "chunk_index": index,
                "text": chunk,
                "token_count": max(1, len(chunk) // 4),
            },
        )


async def seed_knowledge(conn: AsyncConnection, *, tenant_id: str, user_id: str) -> None:
    docs = [
        ("CATALOGO_MODELOS2026.json", "catalogo"),
        ("REQUISITOS2.json", "requisitos"),
    ]
    for filename, category in docs:
        path = REPO_ROOT / "docs" / filename
        if not path.exists():
            continue
        text_value = path.read_text(encoding="utf-8")
        await seed_kb_document(
            conn,
            tenant_id=tenant_id,
            user_id=user_id,
            filename=filename,
            category=category,
            text_value=text_value,
        )


async def seed_branding_and_agent(conn: AsyncConnection, *, tenant_id: str, user_id: str) -> None:
    await conn.execute(
        text(
            "INSERT INTO tenant_branding (tenant_id, bot_name, voice, default_messages) "
            "VALUES (:tenant_id, 'AtendIA', CAST(:voice AS jsonb), CAST(:messages AS jsonb)) "
            "ON CONFLICT (tenant_id) DO UPDATE SET "
            "bot_name=EXCLUDED.bot_name, voice=EXCLUDED.voice, default_messages=EXCLUDED.default_messages"
        ),
        {
            "tenant_id": tenant_id,
            "voice": dumps({"tone": "claro", "style": "breve, humano, sin inventar", "language": "es-MX"}),
            "messages": dumps({"brand_facts": {"safety": "No inventar precios, requisitos ni aprobaciones."}}),
        },
    )
    await conn.execute(text("DELETE FROM agents WHERE tenant_id=:tenant_id"), {"tenant_id": tenant_id})
    await conn.execute(
        text(
            "INSERT INTO agents (tenant_id, name, role, status, behavior_mode, version, goal, style, "
            "tone, language, max_sentences, no_emoji, return_to_flow, is_default, system_prompt, "
            "active_intents, extraction_config, auto_actions, knowledge_config, flow_mode_rules, ops_config) "
            "VALUES (:tenant_id, 'Core Sales Agent', 'sales', 'production', 'normal', 'v1', "
            ":goal, :style, 'claro', 'es-MX', 4, true, true, true, :system_prompt, "
            "CAST(:active_intents AS jsonb), CAST(:extraction_config AS jsonb), "
            "CAST(:auto_actions AS jsonb), CAST(:knowledge_config AS jsonb), "
            "CAST(:flow_mode_rules AS jsonb), CAST(:ops_config AS jsonb))"
        ),
        {
            "tenant_id": tenant_id,
            "goal": "Calificar, cotizar con evidencia, pedir documentos y avanzar pipeline.",
            "style": "Un mensaje breve por turno, natural y progresivo.",
            "system_prompt": "Usa los campos configurados y la KB. No inventes datos sensibles.",
            "active_intents": dumps(["GREETING", "ASK_INFO", "ASK_PRICE", "BUY", "HUMAN_REQUESTED", "UNCLEAR"]),
            "extraction_config": dumps({"fields": ["antiguedad", "tipo_credito", "credito_plan", "modelo_moto"]}),
            "auto_actions": dumps({"pause_on_docs_complete": True}),
            "knowledge_config": dumps({"linked_sources": ["documents"], "selected_tools": ["search_catalog", "lookup_requirements", "lookup_faq"]}),
            "flow_mode_rules": dumps([]),
            "ops_config": dumps({"seeded_by": "bootstrap_tenant", "owner_user_id": user_id}),
        },
    )


async def configure_tenant(conn: AsyncConnection, tenant_id: str, tenant_name: str) -> None:
    await conn.execute(
        text(
            "UPDATE tenants SET name=:name, is_demo=false, config=CAST(:config AS jsonb), "
            "timezone='America/Mexico_City' WHERE id=:tenant_id"
        ),
        {"tenant_id": tenant_id, "name": tenant_name, "config": dumps(TENANT_CONFIG)},
    )


async def main() -> None:
    parser = argparse.ArgumentParser(description="Bootstrap a clean AtendIA tenant.")
    parser.add_argument("--email", default=DEFAULT_EMAIL)
    parser.add_argument("--password", default=DEFAULT_PASSWORD)
    parser.add_argument("--tenant-name", default=DEFAULT_TENANT_NAME)
    parser.add_argument("--reset", action="store_true", help="Delete tenant runtime/config rows first.")
    args = parser.parse_args()

    engine = create_async_engine(get_settings().database_url)
    deleted: dict[str, int] = {}
    try:
        async with engine.begin() as conn:
            tenant_id, user_id = await get_or_create_tenant(
                conn,
                email=args.email,
                password=args.password,
                tenant_name=args.tenant_name,
            )
            if args.reset:
                deleted = await reset_tenant(conn, tenant_id)
            await configure_tenant(conn, tenant_id, args.tenant_name)
            await seed_customer_fields(conn, tenant_id)
            await seed_pipeline(conn, tenant_id)
            await seed_knowledge(conn, tenant_id=tenant_id, user_id=user_id)
            await seed_branding_and_agent(conn, tenant_id=tenant_id, user_id=user_id)

        from sqlalchemy.ext.asyncio import async_sessionmaker

        Session = async_sessionmaker(engine, expire_on_commit=False)
        async with Session() as session:
            validation = await validate_pipeline_config(session, UUID(tenant_id), PIPELINE_DEFINITION)
            if validation.critical_count:
                raise RuntimeError(validation.error_message())

        print("Tenant bootstrap complete")
        print(f"  email:     {args.email}")
        print(f"  password:  {args.password}")
        print(f"  tenant_id: {tenant_id}")
        print(f"  user_id:   {user_id}")
        print("  seeded: fields=12 pipeline=1 docs=8 kb=2 agent=1 qos=max_messages_per_turn=1")
        if deleted:
            print("  reset rows:")
            for table_name, count in deleted.items():
                if count:
                    print(f"    {table_name}: {count}")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(130)
