"""Generic starter pipeline for tenants that don't have one yet.

When a tenant first receives a message — through any of the webhook
paths — the runner needs to know which stage a new conversation should
land in. The pipeline-loader fallback used to return the literal string
``"greeting"``, but that stage doesn't exist in any sensible pipeline,
so conversations got stranded in a stage neither the operator nor the
evaluator recognized.

This module solves that for *every* tenant — present and future — by
defining a canonical, vertical-neutral starter pipeline and an
idempotent helper that materializes it the first time it's needed.

Design choices:
* **Five stages, two terminals.** ``nuevo`` → ``contactado`` →
  ``en_proceso`` → ``ganado`` / ``perdido``. Generic enough for any
  funnel (sales, service, support); the operator can rename / reorder
  / add stages through the editor, and ``put_pipeline``'s
  single-version policy means the starter is just overwritten on
  first save.
* **No auto-enter rules.** A starter pipeline shouldn't move
  conversations on its own — that would surprise operators who haven't
  configured anything yet. The cliente-potencial rule from the
  Crédito-Dinamo seed is vertical-specific and stays in
  ``seed_zored_user.py``.
* **Terminals marked.** ``ganado`` and ``perdido`` carry
  ``is_terminal=true`` so once an operator (or a future rule) closes a
  conversation it can't bounce back to the pipeline.
* **Idempotent seeding.** ``ensure_default_pipeline`` checks for an
  active row first and short-circuits if one exists; concurrent
  webhooks for a brand-new tenant fall through the ``ON CONFLICT
  DO NOTHING`` on ``(tenant_id, version)`` rather than racing each
  other into duplicate rows.
"""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.db.models.tenant_config import TenantPipeline

# The canonical definition. Kept as a plain dict so it matches the JSONB
# shape stored in `tenant_pipelines.definition` directly — no Pydantic
# round-trip needed on the hot path. The shape is validated against
# `PipelineDefinition` in the unit tests.
DEFAULT_PIPELINE_DEFINITION: dict = {
    "version": 1,
    "stages": [
        {
            "id": "nuevo",
            "label": "Nuevo",
            "color": "#6366f1",
            "timeout_hours": 24,
        },
        {
            "id": "contactado",
            "label": "Contactado",
            "color": "#3b82f6",
            "timeout_hours": 48,
        },
        {
            "id": "en_proceso",
            "label": "En proceso",
            "color": "#f59e0b",
            "timeout_hours": 72,
        },
        {
            "id": "ganado",
            "label": "Ganado",
            "color": "#10b981",
            "is_terminal": True,
        },
        {
            "id": "perdido",
            "label": "Perdido",
            "color": "#ef4444",
            "is_terminal": True,
        },
    ],
    "fallback": "ask_clarification",
    "nlu": {"history_turns": 2},
    "composer": {"history_turns": 2},
    "flow_mode_rules": [],
    "docs_per_plan": {},
    # Document catalog is intentionally empty — each tenant authors
    # their own list through the editor ("Catálogo de documentos"
    # section). Shipping a starter list locks tenants into Mexican
    # credit defaults that aren't applicable to motos, gym, services,
    # etc. The runtime path is unaffected: a tenant can still save a
    # pipeline that *references* DOCS_* keys in auto_enter_rules; the
    # contact panel falls back to humanize_doc_key for any key not in
    # the catalog.
    "documents_catalog": [],
}


async def ensure_default_pipeline(session: AsyncSession, tenant_id: UUID) -> bool:
    """Make sure the tenant has an active pipeline row; seed if not.

    Returns ``True`` when a fresh starter row was inserted, ``False``
    when an active pipeline already existed. Caller decides what to do
    with the bool — the runner doesn't care; the audit log might.

    Safe to call from any code path; idempotent under concurrent
    callers thanks to the unique constraint on ``(tenant_id, version)``
    and the ``ON CONFLICT DO NOTHING`` guard.
    """
    existing = (
        await session.execute(
            select(TenantPipeline.id)
            .where(
                TenantPipeline.tenant_id == tenant_id,
                TenantPipeline.active.is_(True),
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return False

    stmt = (
        pg_insert(TenantPipeline)
        .values(
            tenant_id=tenant_id,
            version=1,
            definition=DEFAULT_PIPELINE_DEFINITION,
            active=True,
        )
        .on_conflict_do_nothing(index_elements=["tenant_id", "version"])
    )
    await session.execute(stmt)
    return True
