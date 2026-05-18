"""053_pipeline_mode_prompts_backfill

Revision ID: s5g6h7i8j9k0
Revises: r4f5g6h7i8j9
Create Date: 2026-05-16

Multi-tenant generalization. The composer no longer hardcodes the moto
playbook: it reads per-tenant guidance from
``PipelineDefinition.mode_prompts`` and falls back to a generic,
vertical-neutral default when a tenant has none.

Until today EVERY tenant got the moto MODE_PROMPTS (a Python constant,
identical for all). After the runner change, a pipeline WITHOUT
``mode_prompts`` would fall to the generic default — i.e. an existing
tenant (Dinamo) would silently regress to a drier bot on deploy.

This data migration freezes current behavior: it backfills the legacy
moto playbook into every ACTIVE pipeline that has no ``mode_prompts``
yet, keyed by FlowMode string values (UPPERCASE: "PLAN", "SALES", …).
Net effect: zero behavior change for anyone running today; only NEW
tenants (created without mode_prompts) get the generic default.

It MUST ship in the same release as the runner/composer change — that
is the whole point of the migration (atomic non-regression).

Idempotent: only rows whose ``mode_prompts`` is absent/empty are
touched, so re-running (or a tenant that later authored its own) is
never overwritten.
"""

from __future__ import annotations

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "s5g6h7i8j9k0"
down_revision: str | Sequence[str] | None = "r4f5g6h7i8j9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Import the legacy playbook at migration time. This migration is
    # released atomically with the runner/composer change, so MODE_PROMPTS
    # here == the exact text every tenant got before the change == true
    # non-regression. (Migrations run once; this captures that snapshot.)
    from atendia.contracts.flow_mode import FlowMode
    from atendia.runner.composer_prompts import MODE_PROMPTS

    legacy = {fm.value: MODE_PROMPTS[fm] for fm in FlowMode}

    op.get_bind().execute(
        sa.text(
            """
            UPDATE tenant_pipelines
            SET definition = jsonb_set(
                definition, '{mode_prompts}', CAST(:mp AS jsonb), true
            )
            WHERE active = true
              AND COALESCE(definition->'mode_prompts', '{}'::jsonb) = '{}'::jsonb
            """
        ),
        {"mp": json.dumps(legacy)},
    )


def downgrade() -> None:
    # Best-effort inverse: strip the backfilled key from active rows.
    # (Cannot distinguish backfilled vs tenant-authored after the fact;
    # downgrade is a rare dev operation and the runner tolerates a
    # missing mode_prompts by falling back to the generic default.)
    op.get_bind().execute(
        sa.text(
            "UPDATE tenant_pipelines SET definition = definition - 'mode_prompts' "
            "WHERE active = true AND definition ? 'mode_prompts'"
        )
    )
