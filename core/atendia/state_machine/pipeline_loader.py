import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.contracts.pipeline_definition import PipelineDefinition
from atendia.db.models import TenantPipeline

logger = logging.getLogger(__name__)


class PipelineNotFoundError(Exception):
    """Raised when no active pipeline exists for a tenant."""


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
    return PipelineDefinition.model_validate(row.definition)


async def resolve_initial_stage(session: AsyncSession, tenant_id: UUID) -> str:
    """First stage id for a freshly-created conversation.

    Looks up the tenant's active pipeline and returns ``stages[0].id``. The
    raw-SQL `INSERT INTO conversations` paths in the webhooks and worker
    rely on this so a new conversation lands in a stage that *exists* in
    the tenant's pipeline — the DB column's `server_default='greeting'`
    only fits the demo seed, and any custom pipeline (e.g. Crédito Dinamo)
    that doesn't define a `greeting` stage strands the conversation in a
    state the evaluator can't recognize.

    Falls back to ``'greeting'`` when the tenant has no pipeline so the
    legacy demo flow stays intact.
    """
    try:
        pipeline = await load_active_pipeline(session, tenant_id)
    except PipelineNotFoundError:
        logger.warning(
            "resolve_initial_stage: no active pipeline for tenant=%s; "
            "falling back to 'greeting'",
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
