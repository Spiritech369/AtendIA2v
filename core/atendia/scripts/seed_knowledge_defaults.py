"""Seed Knowledge Base defaults for a tenant — idempotent.

Run once after applying migrations 031-036 (or any time the operator wants
the defaults restored). Inserts:

* 9 collections referenced by the default agent-permission matrix
  (requisitos, ubicacion, dudas_basicas, catalogo, credito, promociones,
  garantias, entrega, servicio).
* 4 ``kb_agent_permissions`` rows — one per agent (recepcionista,
  sales_agent, duda_general, postventa) with the design-doc-specified
  source_types / collection_slugs / can_quote_* / required_customer_fields.
* 1 ``kb_safe_answer_settings`` row with the seeded risky_phrases regex
  list and the Spanish-MX default fallback message.
* 3 ``kb_source_priority_rules`` rows (faq=100, catalog=80, document=60,
  agent NULL = applies to all agents).

Re-running the script never adds duplicates (UNIQUE constraints on
collections/agent_permissions, PK on safe_answer_settings, SELECT-then-
INSERT guard on priority rules which has no unique index).

Usage:
    cd core
    uv run python -m atendia.scripts.seed_knowledge_defaults <tenant_uuid>
"""

from __future__ import annotations

import asyncio
import sys
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from atendia.config import get_settings


DEFAULT_COLLECTIONS: list[dict[str, Any]] = [
    {"slug": "requisitos", "name": "Requisitos", "icon": "FileText", "color": "blue"},
    {"slug": "ubicacion", "name": "Ubicación", "icon": "MapPin", "color": "emerald"},
    {"slug": "dudas_basicas", "name": "Dudas básicas", "icon": "HelpCircle", "color": "slate"},
    {"slug": "catalogo", "name": "Catálogo", "icon": "Car", "color": "violet"},
    {"slug": "credito", "name": "Crédito", "icon": "CreditCard", "color": "amber"},
    {"slug": "promociones", "name": "Promociones", "icon": "Tag", "color": "rose"},
    {"slug": "garantias", "name": "Garantías", "icon": "ShieldCheck", "color": "teal"},
    {"slug": "entrega", "name": "Entrega", "icon": "Truck", "color": "cyan"},
    {"slug": "servicio", "name": "Servicio", "icon": "Wrench", "color": "orange"},
]

DEFAULT_AGENT_PERMISSIONS: list[dict[str, Any]] = [
    {
        "agent": "recepcionista",
        "allowed_source_types": ["faq"],
        "allowed_collection_slugs": ["requisitos", "ubicacion", "dudas_basicas"],
        "min_score": 0.7,
        "can_quote_prices": False,
        "can_quote_stock": False,
        "required_customer_fields": [],
        "escalate_on_conflict": True,
    },
    {
        "agent": "sales_agent",
        "allowed_source_types": ["faq", "catalog", "document"],
        "allowed_collection_slugs": ["catalogo", "credito", "promociones"],
        "min_score": 0.7,
        "can_quote_prices": True,
        "can_quote_stock": True,
        "required_customer_fields": ["tipo_credito", "plan_credito"],
        "escalate_on_conflict": True,
    },
    {
        "agent": "duda_general",
        "allowed_source_types": ["faq", "document"],
        "allowed_collection_slugs": ["requisitos", "garantias", "ubicacion", "credito"],
        "min_score": 0.7,
        "can_quote_prices": False,
        "can_quote_stock": False,
        "required_customer_fields": [],
        "escalate_on_conflict": True,
    },
    {
        "agent": "postventa",
        "allowed_source_types": ["faq", "document"],
        "allowed_collection_slugs": ["garantias", "entrega", "servicio"],
        "min_score": 0.7,
        "can_quote_prices": False,
        "can_quote_stock": False,
        "required_customer_fields": [],
        "escalate_on_conflict": True,
    },
]

DEFAULT_RISKY_PHRASES: list[dict[str, str]] = [
    {"pattern": r"crédito\s+aprobado", "rewrite": "Podemos revisar tu crédito"},
    {"pattern": r"aprobado\s+seguro", "rewrite": "Sujeto a validación"},
    {"pattern": r"sin\s+revisar\s+buró", "rewrite": "Sujeto a evaluación crediticia"},
    {"pattern": r"entrega\s+garantizada", "rewrite": "Sujeto a disponibilidad"},
    {"pattern": r"precio\s+fijo", "rewrite": "Depende del plan y documentación"},
    {
        "pattern": r"no\s+necesitas\s+comprobar\s+ingresos",
        "rewrite": "Un asesor confirma documentación",
    },
]

DEFAULT_PRIORITY_RULES: list[dict[str, Any]] = [
    {"source_type": "faq", "priority": 100, "minimum_score": 0.7},
    {"source_type": "catalog", "priority": 80, "minimum_score": 0.7},
    {"source_type": "document", "priority": 60, "minimum_score": 0.7},
]


async def seed_for_tenant(session: AsyncSession, tenant_id: UUID) -> dict[str, int]:
    """Seed defaults for one tenant. Returns counts of rows touched per kind."""
    counts = {"collections": 0, "agent_permissions": 0, "safe_answer": 0, "priority_rules": 0}

    # 1) Collections — UNIQUE(tenant_id, slug).
    for coll in DEFAULT_COLLECTIONS:
        result = await session.execute(
            text(
                "INSERT INTO kb_collections (tenant_id, name, slug, icon, color) "
                "VALUES (:t, :name, :slug, :icon, :color) "
                "ON CONFLICT (tenant_id, slug) DO NOTHING "
                "RETURNING id"
            ),
            {"t": tenant_id, **coll},
        )
        if result.scalar_one_or_none() is not None:
            counts["collections"] += 1

    # 2) Agent permissions — UNIQUE(tenant_id, agent).
    for perm in DEFAULT_AGENT_PERMISSIONS:
        result = await session.execute(
            text(
                "INSERT INTO kb_agent_permissions ("
                "tenant_id, agent, allowed_source_types, allowed_collection_slugs, "
                "min_score, can_quote_prices, can_quote_stock, "
                "required_customer_fields, escalate_on_conflict"
                ") VALUES ("
                ":t, :agent, :sources, :colls, :min_score, :prices, :stock, "
                ":req_fields, :escalate"
                ") ON CONFLICT (tenant_id, agent) DO NOTHING "
                "RETURNING id"
            ),
            {
                "t": tenant_id,
                "agent": perm["agent"],
                "sources": perm["allowed_source_types"],
                "colls": perm["allowed_collection_slugs"],
                "min_score": perm["min_score"],
                "prices": perm["can_quote_prices"],
                "stock": perm["can_quote_stock"],
                "req_fields": perm["required_customer_fields"],
                "escalate": perm["escalate_on_conflict"],
            },
        )
        if result.scalar_one_or_none() is not None:
            counts["agent_permissions"] += 1

    # 3) Safe-answer settings — tenant_id is PK.
    import json

    result = await session.execute(
        text(
            "INSERT INTO kb_safe_answer_settings ("
            "tenant_id, risky_phrases"
            ") VALUES (:t, CAST(:rp AS JSONB)) "
            "ON CONFLICT (tenant_id) DO NOTHING "
            "RETURNING tenant_id"
        ),
        {"t": tenant_id, "rp": json.dumps(DEFAULT_RISKY_PHRASES)},
    )
    if result.scalar_one_or_none() is not None:
        counts["safe_answer"] += 1

    # 4) Priority rules — no unique constraint; SELECT-then-INSERT guard.
    for rule in DEFAULT_PRIORITY_RULES:
        existing = await session.execute(
            text(
                "SELECT id FROM kb_source_priority_rules "
                "WHERE tenant_id = :t AND agent IS NULL AND source_type = :st"
            ),
            {"t": tenant_id, "st": rule["source_type"]},
        )
        if existing.scalar_one_or_none() is None:
            await session.execute(
                text(
                    "INSERT INTO kb_source_priority_rules ("
                    "tenant_id, agent, source_type, priority, minimum_score"
                    ") VALUES (:t, NULL, :st, :pri, :ms)"
                ),
                {
                    "t": tenant_id,
                    "st": rule["source_type"],
                    "pri": rule["priority"],
                    "ms": rule["minimum_score"],
                },
            )
            counts["priority_rules"] += 1

    await session.commit()
    return counts


async def _main(tenant_id_str: str) -> int:
    tenant_id = UUID(tenant_id_str)
    engine = create_async_engine(get_settings().database_url)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    try:
        async with Session() as session:
            counts = await seed_for_tenant(session, tenant_id)
        print(f"Seeded tenant {tenant_id}: {counts}")
        return 0
    finally:
        await engine.dispose()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(
            f"Usage: python -m atendia.scripts.seed_knowledge_defaults <tenant_uuid>",
            file=sys.stderr,
        )
        sys.exit(2)
    sys.exit(asyncio.run(_main(sys.argv[1])))
