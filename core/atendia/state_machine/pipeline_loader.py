import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.contracts.pipeline_definition import PipelineDefinition
from atendia.db.models import TenantPipeline

logger = logging.getLogger(__name__)


class PipelineNotFoundError(Exception):
    """Raised when no active pipeline exists for a tenant."""


def _normalize_legacy_auto_enter_rules(definition: dict) -> dict:
    """Accept persisted pre-contract rule lists without weakening the model.

    Older pipeline seeds stored ``stage.auto_enter_rules`` directly as a
    condition list. The current contract stores a rule group object with
    ``enabled``, ``match``, and ``conditions``. Normalize only that legacy
    JSONB shape before Pydantic validation so loaded pipelines remain readable
    while new writes keep the stricter contract.
    """
    stages = definition.get("stages")
    if not isinstance(stages, list):
        return definition

    normalized_stages = []
    changed = False
    for stage in stages:
        if not isinstance(stage, dict):
            normalized_stages.append(stage)
            continue
        rules = stage.get("auto_enter_rules")
        if not isinstance(rules, list):
            normalized_stages.append(stage)
            continue

        changed = True
        replacement = None
        if rules:
            replacement = {"enabled": True, "match": "all", "conditions": rules}
        normalized_stages.append({**stage, "auto_enter_rules": replacement})

    if not changed:
        return definition
    return {**definition, "stages": normalized_stages}


async def load_active_pipeline(session: AsyncSession, tenant_id: UUID) -> PipelineDefinition:
    stmt = (
        select(TenantPipeline)
        .where(TenantPipeline.tenant_id == tenant_id, TenantPipeline.active.is_(True))
        .order_by(TenantPipeline.version.desc())
        .limit(1)
    )
    result = await session.execute(stmt)
    row = result.scalar_one_or_none()
    if row is None:
        raise PipelineNotFoundError(f"no active pipeline for tenant {tenant_id}")
    definition = _normalize_legacy_auto_enter_rules(dict(row.definition or {}))
    definition.setdefault("version", row.version)
    return PipelineDefinition.model_validate(definition)


async def resolve_initial_stage(session: AsyncSession, tenant_id: UUID) -> str:
    """First stage id for a freshly-created conversation.

    Looks up the tenant's active pipeline and returns ``stages[0].id``.
    If the tenant has no active pipeline yet — a brand-new signup that
    hasn't published one — this seeds the generic starter pipeline
    from :mod:`atendia.state_machine.default_pipeline` so the
    conversation lands in a real stage instead of the ghost
    ``"greeting"`` value the DB column still server-defaults to. The
    seeded pipeline is editable / replaceable; the next ``PUT
    /tenants/pipeline`` overwrites it under the single-version policy.

    The empty-stages defensive fallback still returns ``"greeting"``
    because that case implies a manually-corrupted definition — the
    operator needs to notice it, and crashing further down the runner
    is worse than logging and continuing with the database default.
    """
    from atendia.state_machine.default_pipeline import (
        ensure_default_pipeline,
    )

    try:
        pipeline = await load_active_pipeline(session, tenant_id)
    except PipelineNotFoundError:
        seeded = await ensure_default_pipeline(session, tenant_id)
        if seeded:
            logger.info(
                "resolve_initial_stage: seeded starter pipeline for tenant=%s",
                tenant_id,
            )
        # Re-load — another concurrent caller may have seeded it under us.
        try:
            pipeline = await load_active_pipeline(session, tenant_id)
        except PipelineNotFoundError:
            logger.warning(
                "resolve_initial_stage: seeding starter pipeline for "
                "tenant=%s failed; falling back to 'greeting'",
                tenant_id,
            )
            return "greeting"
    if not pipeline.stages:
        logger.warning(
            "resolve_initial_stage: active pipeline for tenant=%s has empty "
            "stages list; falling back to 'greeting'",
            tenant_id,
        )
        return "greeting"
    stage_id = pipeline.stages[0].id
    logger.info(
        "resolve_initial_stage: tenant=%s pipeline_version=%s first_stage=%s",
        tenant_id,
        pipeline.version,
        stage_id,
    )
    return stage_id
