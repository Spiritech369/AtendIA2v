"""One-shot seed: create a fresh tenant + superadmin user + starter
"Crédito Dinamo" pipeline with auto_enter_rules wired up.

For manual QA — gives the user a clean slate to walk through the whole
product. The new tenant has `is_demo=False` so it does NOT receive the
auto-seeded demo customers / agents / workflows that the demo tenant
gets. The pipeline DOES get seeded so the runner has something to read
on first inbound (without a pipeline, the conversation runner raises
PipelineNotFoundError).

Run from `core/`:
    uv run python scripts/seed_zored_user.py
"""

from __future__ import annotations

import asyncio
import json
import sys

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from atendia.api._auth_helpers import hash_password
from atendia.config import get_settings

EMAIL = "dele.zored@hotmail.com"
PASSWORD = "dinamo123"
ROLE = "superadmin"
TENANT_NAME = "Zored QA Workspace"

# Starter pipeline. Mirrors the user's spec:
#   - "Cliente Potencial" fires when modelo_interes + plan_credito +
#     tipo_enganche are all present in customer.attrs.
#   - "Papelería completa" fires when all four document statuses are ok.
# Operators can edit or delete any of these — they're just a sane
# default, not load-bearing for any other code path.
CREDITO_DINAMO_PIPELINE = {
    "version": 1,
    "fallback": "escalate_to_human",
    "stages": [
        {
            "id": "nuevo",
            "label": "Nuevo lead",
            "color": "#6366f1",
            "timeout_hours": 24,
        },
        {
            "id": "cliente_potencial",
            "label": "Cliente Potencial",
            "color": "#3b82f6",
            "timeout_hours": 24,
            "auto_enter_rules": {
                "enabled": True,
                "match": "all",
                "conditions": [
                    {"field": "modelo_interes", "operator": "exists"},
                    {"field": "plan_credito", "operator": "exists"},
                    {"field": "tipo_enganche", "operator": "exists"},
                ],
            },
        },
        {
            "id": "documentos_pendientes",
            "label": "Documentos pendientes",
            "color": "#f59e0b",
            "timeout_hours": 48,
        },
        {
            "id": "papeleria_completa",
            "label": "Papelería completa",
            "color": "#10b981",
            "timeout_hours": 24,
            "auto_enter_rules": {
                "enabled": True,
                "match": "all",
                "conditions": [
                    {"field": "DOCS_INE.status", "operator": "equals", "value": "ok"},
                    {
                        "field": "DOCS_COMPROBANTE_DOMICILIO.status",
                        "operator": "equals",
                        "value": "ok",
                    },
                    {"field": "DOCS_ESTADOS_CUENTA.status", "operator": "equals", "value": "ok"},
                    {"field": "DOCS_RECIBOS_NOMINA.status", "operator": "equals", "value": "ok"},
                ],
            },
        },
        {
            "id": "cerrado",
            "label": "Cerrado",
            "color": "#22c55e",
            "timeout_hours": 0,
            "is_terminal": True,
        },
    ],
    "docs_per_plan": {
        "nomina_tarjeta": [
            "DOCS_INE",
            "DOCS_COMPROBANTE_DOMICILIO",
            "DOCS_ESTADOS_CUENTA",
            "DOCS_RECIBOS_NOMINA",
        ],
        "tradicional": [
            "DOCS_INE",
            "DOCS_COMPROBANTE_DOMICILIO",
            "DOCS_ESTADOS_CUENTA",
        ],
    },
}


async def main() -> None:
    engine = create_async_engine(get_settings().database_url)
    async with engine.begin() as conn:
        # Check if user already exists
        existing = (
            await conn.execute(
                text("SELECT id, tenant_id FROM tenant_users WHERE email = :e"),
                {"e": EMAIL},
            )
        ).first()
        if existing is not None:
            uid, tid = existing
            # Update password just in case
            await conn.execute(
                text("UPDATE tenant_users SET password_hash = :h, role = :r WHERE id = :u"),
                {"h": hash_password(PASSWORD), "r": ROLE, "u": uid},
            )
            # Ensure the starter pipeline exists. Idempotent: if any
            # tenant_pipelines row exists for this tenant, we leave it
            # untouched (the operator may have customised it). Only seed
            # when truly empty.
            pipeline_count = (
                await conn.execute(
                    text("SELECT COUNT(*) FROM tenant_pipelines WHERE tenant_id = :t"),
                    {"t": tid},
                )
            ).scalar_one()
            seeded_pipeline = False
            if int(pipeline_count or 0) == 0:
                await conn.execute(
                    text(
                        "INSERT INTO tenant_pipelines "
                        "(tenant_id, version, definition, active) "
                        "VALUES (:t, 1, :def\\:\\:jsonb, true)"
                    ),
                    {"t": tid, "def": json.dumps(CREDITO_DINAMO_PIPELINE)},
                )
                seeded_pipeline = True

            print(f"User already exists: {EMAIL}")
            print(f"  tenant_id: {tid}")
            print(f"  user_id:   {uid}")
            print(f"  password reset to: {PASSWORD}")
            print(
                f"  starter pipeline: {'seeded (was empty)' if seeded_pipeline else 'already present'}"
            )
            return

        # Create a fresh tenant — explicitly NOT a demo so no auto-seeding.
        tenant_id = (
            await conn.execute(
                text("INSERT INTO tenants (name, is_demo) VALUES (:n, false) RETURNING id"),
                {"n": TENANT_NAME},
            )
        ).scalar()

        user_id = (
            await conn.execute(
                text(
                    "INSERT INTO tenant_users (tenant_id, email, role, password_hash) "
                    "VALUES (:t, :e, :r, :h) RETURNING id"
                ),
                {
                    "t": tenant_id,
                    "e": EMAIL,
                    "r": ROLE,
                    "h": hash_password(PASSWORD),
                },
            )
        ).scalar()

        # Seed a minimal tenant_branding row so the branding API doesn't 404.
        await conn.execute(
            text("INSERT INTO tenant_branding (tenant_id) VALUES (:t)"),
            {"t": tenant_id},
        )

        # Seed the starter Crédito Dinamo pipeline. Without an active
        # pipeline, the runner would raise PipelineNotFoundError on the
        # first inbound, so this is the difference between "fresh tenant
        # ready for QA" and "fresh tenant that 500s on the first WhatsApp
        # message".
        await conn.execute(
            text(
                "INSERT INTO tenant_pipelines (tenant_id, version, definition, active) "
                "VALUES (:t, 1, :def\\:\\:jsonb, true)"
            ),
            {"t": tenant_id, "def": json.dumps(CREDITO_DINAMO_PIPELINE)},
        )

    await engine.dispose()

    print("Created fresh workspace + superadmin user + starter pipeline.")
    print(f"  email:     {EMAIL}")
    print(f"  password:  {PASSWORD}")
    print(f"  role:      {ROLE}")
    print(f"  tenant_id: {tenant_id}")
    print(f"  user_id:   {user_id}")
    print()
    print("Pipeline 'Crédito Dinamo' v1 seeded with:")
    for stage in CREDITO_DINAMO_PIPELINE["stages"]:
        rules = stage.get("auto_enter_rules")
        marker = " (auto)" if rules and rules.get("enabled") else ""
        terminal = " [terminal]" if stage.get("is_terminal") else ""
        print(f"  - {stage['id']}: {stage['label']}{marker}{terminal}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(130)
