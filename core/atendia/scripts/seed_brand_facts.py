"""Seed `brand_facts` into `tenant_branding.default_messages` JSONB (Phase 3c.2 / T23).

The composer's MODE_PROMPTS reference `{{brand_facts.X}}` placeholders that the
runner resolves before sending the system prompt to gpt-4o. Without this seed,
PLAN/SALES/DOC/SUPPORT modes leak literal `{{brand_facts.catalog_url}}` into
the model — the pre-pass treats empty facts as a no-op so the prompt still
renders, but answers about catalog/address/timing become hand-wavey.

Usage:
    PYTHONIOENCODING=utf-8 PYTHONPATH=. uv run python -m atendia.scripts.seed_brand_facts \
        --tenant-name dinamomotos

The script:
  * Resolves the tenant by name (UUIDs are environment-specific so we don't
    hardcode them here).
  * UPSERTs into tenant_branding so a fresh tenant without a branding row
    still gets seeded.
  * jsonb_set merges into existing default_messages so other keys (welcome
    messages, etc.) are preserved.
  * Prints affected row count and exits non-zero on missing tenant — silent
    no-ops are exactly how stale prompts ship to production.
"""

import argparse
import asyncio
import json
import sys

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from atendia.config import get_settings

# Hardcoded for now — Dinamo is the only tenant in 3c.2. When we onboard a
# second tenant, refactor to read from a YAML file passed via --facts-file.
_DINAMO_BRAND_FACTS = {
    "address": "Benito Juárez 801, Centro Monterrey",
    "approval_time_hours": "24",
    "buro_max_amount": "$50 mil",
    "catalog_url": "https://dinamomotos.com/catalogo.html",
    "delivery_time_days": "3-7",
    "human_agent_name": "Francisco",
    "post_completion_form": "https://forms.gle/U1MEueL63vgftiuZ8",
    "wa_catalog_link": "https://wa.me/c/5218128889241",
}


async def _seed(tenant_name: str, brand_facts: dict) -> int:
    engine = create_async_engine(get_settings().database_url)
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessionmaker() as session:
            tenant_id = (
                await session.execute(
                    text("SELECT id FROM tenants WHERE name = :n"),
                    {"n": tenant_name},
                )
            ).scalar()
            if tenant_id is None:
                print(f"ERROR: tenant {tenant_name!r} not found", file=sys.stderr)
                return 0

            # UPSERT preserves any default_messages the tenant_branding row
            # already carries (welcome message, etc.) and merges brand_facts in.
            result = await session.execute(
                text("""
                    INSERT INTO tenant_branding (tenant_id, bot_name, voice, default_messages)
                    VALUES (
                        :tid, 'Asistente', '{}'::jsonb,
                        jsonb_build_object('brand_facts', CAST(:bf AS jsonb))
                    )
                    ON CONFLICT (tenant_id) DO UPDATE SET
                        default_messages = jsonb_set(
                            COALESCE(tenant_branding.default_messages, '{}'::jsonb),
                            '{brand_facts}',
                            CAST(:bf AS jsonb)
                        )
                """),
                {"tid": tenant_id, "bf": json.dumps(brand_facts)},
            )
            await session.commit()
            return result.rowcount or 0
    finally:
        await engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--tenant-name",
        required=True,
        help="Tenant name in the `tenants` table (e.g. dinamomotos).",
    )
    args = parser.parse_args()

    rows = asyncio.run(_seed(args.tenant_name, _DINAMO_BRAND_FACTS))
    if rows == 0:
        return 1
    print(f"OK: brand_facts seeded for {args.tenant_name!r} ({rows} row affected).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
