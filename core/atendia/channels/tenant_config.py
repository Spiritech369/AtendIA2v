from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.db.models import Tenant


class MetaTenantConfigNotFoundError(Exception):
    """Raised when a tenant has no `meta` section in its config JSONB,
    or the section is missing required fields, or the tenant doesn't exist.
    """


class MetaTenantConfig(BaseModel):
    phone_number_id: str
    verify_token: str


async def load_meta_config(session: AsyncSession, tenant_id: UUID) -> MetaTenantConfig:
    stmt = select(Tenant).where(Tenant.id == tenant_id)
    tenant = (await session.execute(stmt)).scalar_one_or_none()
    if tenant is None:
        raise MetaTenantConfigNotFoundError(f"tenant not found: {tenant_id}")
    meta = (tenant.config or {}).get("meta")
    if not meta or "phone_number_id" not in meta or "verify_token" not in meta:
        raise MetaTenantConfigNotFoundError(
            f"tenant {tenant_id} has no `meta.phone_number_id` and `meta.verify_token`"
        )
    return MetaTenantConfig.model_validate(meta)
