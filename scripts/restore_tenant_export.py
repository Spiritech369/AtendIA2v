"""Restore a tenant from a JSON export.

Usage from repo root:

    cd core
    uv run python ../scripts/restore_tenant_export.py \
      --file ../docs/tenant_exports/dinamomotosnl.atendia-tenant.json \
      --password "change-me"

The export intentionally does not store password hashes. This script creates the
tenant admin user with the password supplied at restore time.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import text

REPO_ROOT = Path(__file__).resolve().parents[1]
CORE_DIR = REPO_ROOT / "core"
if str(CORE_DIR) not in sys.path:
    sys.path.insert(0, str(CORE_DIR))

from atendia.api._auth_helpers import hash_password  # noqa: E402
from atendia.db.session import _get_factory  # noqa: E402

RESET_TABLES = [
    "workflow_dependencies",
    "workflow_variables",
    "workflow_versions",
    "workflows",
    "knowledge_chunks",
    "knowledge_documents",
    "kb_source_priority_rules",
    "kb_agent_permissions",
    "kb_safe_answer_settings",
    "kb_collections",
    "tenant_catalogs",
    "tenant_faqs",
    "customer_field_definitions",
    "agents",
    "ai_agents",
    "knowledge_base_sources",
    "tenant_templates_meta",
    "tenant_tools_config",
    "tenant_baileys_config",
    "tenant_branding",
    "tenant_pipelines",
]

INSERT_ORDER = [
    "tenant_branding",
    "tenant_baileys_config",
    "tenant_tools_config",
    "tenant_templates_meta",
    "tenant_pipelines",
    "agents",
    "customer_field_definitions",
    "kb_collections",
    "kb_safe_answer_settings",
    "kb_agent_permissions",
    "kb_source_priority_rules",
    "tenant_catalogs",
    "tenant_faqs",
    "knowledge_documents",
    "knowledge_chunks",
    "workflows",
    "workflow_versions",
    "workflow_variables",
    "workflow_dependencies",
    "ai_agents",
    "knowledge_base_sources",
]


def _json_param(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


async def _insert_row(session, table: str, row: dict[str, Any]) -> None:
    columns = list(row.keys())
    quoted_columns = ", ".join(f'"{column}"' for column in columns)
    values = ", ".join(f":{column}" for column in columns)
    await session.execute(
        text(f'INSERT INTO "{table}" ({quoted_columns}) VALUES ({values})'),
        row,
    )


async def restore(path: Path, password: str, *, reset: bool) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    tenant = payload["tenant"]
    user = payload["tenant_user"]
    tenant_id = tenant["id"]
    email = user["email"]

    factory = _get_factory()
    async with factory() as session:
        if reset:
            await session.execute(
                text("DELETE FROM tenants WHERE id = :tenant_id"), {"tenant_id": tenant_id}
            )
            await session.execute(
                text("DELETE FROM tenant_users WHERE lower(email) = lower(:email)"),
                {"email": email},
            )
        else:
            existing = (
                await session.execute(
                    text(
                        "SELECT 1 FROM tenants WHERE id = :tenant_id "
                        "UNION SELECT 1 FROM tenant_users WHERE lower(email) = lower(:email)"
                    ),
                    {"tenant_id": tenant_id, "email": email},
                )
            ).first()
            if existing is not None:
                raise SystemExit(
                    "Tenant or user already exists. Re-run with --reset to replace it."
                )

        await _insert_row(session, "tenants", tenant)

        await _insert_row(
            session,
            "tenant_users",
            {
                "id": user["id"],
                "tenant_id": tenant_id,
                "email": email,
                "role": user.get("role", "tenant_admin"),
                "password_hash": hash_password(password),
            },
        )

        tables = payload.get("tables", {})
        for table in RESET_TABLES:
            if reset and table in tables:
                await session.execute(
                    text(f'DELETE FROM "{table}" WHERE tenant_id = :tenant_id'),
                    {"tenant_id": tenant_id},
                )

        for table in INSERT_ORDER:
            for row in tables.get(table, []):
                await _insert_row(session, table, row)

        await session.commit()

    print("Tenant restored")
    print(f"  email: {email}")
    print(f"  tenant_id: {tenant_id}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Restore an AtendIA tenant export.")
    parser.add_argument("--file", required=True, type=Path)
    parser.add_argument("--password", required=True)
    parser.add_argument(
        "--reset", action="store_true", help="Replace an existing tenant/user if present."
    )
    args = parser.parse_args()
    asyncio.run(restore(args.file, args.password, reset=args.reset))


if __name__ == "__main__":
    main()
