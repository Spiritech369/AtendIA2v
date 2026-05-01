from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.contracts.pipeline_definition import PipelineDefinition
from atendia.db.models import TenantPipeline


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
