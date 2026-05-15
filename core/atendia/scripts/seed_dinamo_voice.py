"""Seed tenant_branding.voice for Dinamo with the agreed-on tone.

Usage:
    PYTHONPATH=. uv run python -m atendia.scripts.seed_dinamo_voice \
        --tenant-id <uuid> [--dry-run]
"""

import argparse
import asyncio
import json
import sys
from uuid import UUID

from sqlalchemy import text

DINAMO_VOICE = {
    "register": "informal_mexicano",
    "use_emojis": "sparingly",
    "max_words_per_message": 40,
    "bot_name": "Dinamo",
    "forbidden_phrases": ["estimado cliente", "le saluda atentamente", "cordialmente"],
    "signature_phrases": ["¡qué onda!", "te paso", "ahí va"],
}


async def _main(tenant_id: UUID, dry_run: bool) -> int:
    from atendia.db.session import _get_factory

    factory = _get_factory()
    async with factory() as session:
        existing = (
            await session.execute(
                text("SELECT 1 FROM tenant_branding WHERE tenant_id = :t"),
                {"t": tenant_id},
            )
        ).fetchone()
        if not existing:
            print(f"No tenant_branding row for {tenant_id}", file=sys.stderr)
            return 1
        print(f"Setting voice for tenant {tenant_id}:")
        print(json.dumps(DINAMO_VOICE, indent=2, ensure_ascii=False))
        if dry_run:
            print("[dry run] not writing")
            return 0
        await session.execute(
            text("UPDATE tenant_branding SET voice = CAST(:v AS jsonb) WHERE tenant_id = :t"),
            {"v": json.dumps(DINAMO_VOICE), "t": tenant_id},
        )
        await session.commit()
        return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant-id", type=UUID, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    sys.exit(asyncio.run(_main(args.tenant_id, args.dry_run)))
