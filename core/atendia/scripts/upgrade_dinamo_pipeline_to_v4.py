"""Upgrade Dinamo's tenant_pipelines row to schema v4.

Usage:
    PYTHONPATH=. uv run python -m atendia.scripts.upgrade_dinamo_pipeline_to_v4 \
        --tenant-id <uuid> [--dry-run]

Writes a NEW row with version=N+1, active=true. Old row becomes active=false.
Idempotent if the active pipeline is already v4.
"""
from __future__ import annotations

import argparse
import asyncio
import copy
import json
import sys
from typing import Any
from uuid import UUID

from sqlalchemy import text


# Edited by humans: descriptions used by the NLU prompt.
DINAMO_FIELD_DESCRIPTIONS: dict[str, str] = {
    "interes_producto": "Modelo de motocicleta o categoría que le interesa al cliente (ej: 150Z, scooter, deportiva)",
    "ciudad": "Ciudad donde reside el cliente, en México",
    "nombre": "Nombre del cliente",
    "presupuesto_max": "Tope máximo en MXN (numérico)",
}


def _coerce_field(s: Any) -> dict[str, str]:
    if isinstance(s, str):
        return {"name": s, "description": DINAMO_FIELD_DESCRIPTIONS.get(s, "")}
    return s


def upgrade_pipeline_jsonb(old: dict[str, Any]) -> dict[str, Any]:
    """Transform a pipeline JSONB to schema v4. Idempotent.

    - Sets version=4 if not already.
    - Adds nlu={history_turns: 4} if absent.
    - Coerces required_fields and optional_fields strings -> {name, description}
      using DINAMO_FIELD_DESCRIPTIONS as the description source.
    """
    if old.get("version") == 4 and "nlu" in old:
        return old  # already migrated
    new = copy.deepcopy(old)
    new["version"] = 4
    new.setdefault("nlu", {"history_turns": 4})
    for stage in new.get("stages", []):
        for key in ("required_fields", "optional_fields"):
            specs = stage.get(key, [])
            stage[key] = [_coerce_field(s) for s in specs]
    return new


async def _main(tenant_id: UUID, dry_run: bool) -> int:
    # IO boundary: imports DB session lazily so unit tests don't pull in DB config.
    from atendia.db.session import _get_factory  # type: ignore[attr-defined]

    factory = _get_factory()
    async with factory() as session:
        row = (await session.execute(
            text("SELECT id, version, definition FROM tenant_pipelines "
                 "WHERE tenant_id = :t AND active = true LIMIT 1"),
            {"t": tenant_id},
        )).fetchone()
        if not row:
            print(f"No active pipeline for tenant {tenant_id}", file=sys.stderr)
            return 1
        _id, current_version, definition = row
        new_def = upgrade_pipeline_jsonb(definition)
        if new_def is definition or (
            definition.get("version") == 4 and "nlu" in definition
        ):
            print(f"Pipeline for tenant {tenant_id} is already v4. No-op.")
            return 0
        new_version = current_version + 1
        print(f"Old version: {current_version}, new version: {new_version}")
        print(json.dumps(new_def, indent=2, ensure_ascii=False))
        if dry_run:
            print("[dry run] not writing")
            return 0
        await session.execute(
            text("UPDATE tenant_pipelines SET active = false WHERE id = :id"),
            {"id": _id},
        )
        await session.execute(
            text("INSERT INTO tenant_pipelines (tenant_id, version, definition, active) "
                 "VALUES (:t, :v, CAST(:d AS jsonb), true)"),
            {"t": tenant_id, "v": new_version, "d": json.dumps(new_def)},
        )
        await session.commit()
        return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant-id", type=UUID, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    sys.exit(asyncio.run(_main(args.tenant_id, args.dry_run)))
