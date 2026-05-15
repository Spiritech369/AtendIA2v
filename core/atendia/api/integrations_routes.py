"""Read-only views over a tenant's external integrations.

Right now we expose just enough metadata for the operator to wire a Meta
WhatsApp Cloud API account into the system. Credentials are *not* mutable
through this endpoint — that flow involves Meta Business Manager OAuth and
is out of scope for the v1-parity sprint.

The plain-text fields (``verify_token``) are restricted to ``tenant_admin``
roles; operators only see the metadata they need to triage issues.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.api._auth_helpers import AuthUser
from atendia.api._deps import current_tenant_id, current_user
from atendia.config import get_settings
from atendia.db.models.tenant import Tenant
from atendia.db.session import get_db_session
from atendia.queue.circuit_breaker import is_open

router = APIRouter()


class WhatsAppDetails(BaseModel):
    phone_number: str | None
    business_name: str | None
    phone_number_id: str | None
    business_id: str | None
    # Tenant-admin-only: the Meta webhook verification token the operator must
    # paste into Meta Business Manager. Empty string for non-admin callers.
    verify_token: str | None
    # Path to register in Meta Business Manager. The frontend prefixes
    # ``window.location.origin`` to build the full URL since the backend
    # doesn't know its public hostname.
    webhook_path: str
    last_webhook_at: datetime | None
    circuit_breaker_open: bool


class AIProviderInfo(BaseModel):
    """Read-only view of which LLM/NLU providers are wired up. Useful for
    triage when the agent stops responding — ops want to know whether the
    deployment is on the keyword fallback or hitting OpenAI."""

    nlu_provider: str
    nlu_model: str
    composer_provider: str
    composer_model: str
    has_openai_key: bool


@router.get("/whatsapp/details", response_model=WhatsAppDetails)
async def get_whatsapp_details(
    user: AuthUser = Depends(current_user),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> WhatsAppDetails:
    row = (await session.execute(select(Tenant).where(Tenant.id == tenant_id))).scalar_one()
    config = row.config or {}
    meta = config.get("meta", {}) if isinstance(config, dict) else {}

    is_admin = user.role in {"tenant_admin", "superadmin"}
    raw_token = meta.get("verify_token") if isinstance(meta, dict) else None
    verify_token = raw_token if (is_admin and raw_token) else None

    redis = Redis.from_url(get_settings().redis_url)
    try:
        cb_open = await is_open(redis, str(tenant_id))
        raw_ts = await redis.get(f"webhook:last_at:{tenant_id}")
    finally:
        await redis.aclose()
    last_webhook_at: datetime | None = None
    if raw_ts:
        last_webhook_at = datetime.fromisoformat(raw_ts.decode())

    return WhatsAppDetails(
        phone_number=meta.get("phone_number") or config.get("phone_number"),
        business_name=meta.get("business_name") or row.name,
        phone_number_id=meta.get("phone_number_id") or config.get("phone_number_id"),
        business_id=row.meta_business_id,
        verify_token=verify_token,
        webhook_path=f"/webhooks/meta/{tenant_id}",
        last_webhook_at=last_webhook_at,
        circuit_breaker_open=cb_open,
    )


@router.get("/ai-provider", response_model=AIProviderInfo)
async def get_ai_provider_info(
    user: AuthUser = Depends(current_user),  # noqa: ARG001
    tenant_id: UUID = Depends(current_tenant_id),  # noqa: ARG001
) -> AIProviderInfo:
    settings = get_settings()
    return AIProviderInfo(
        nlu_provider=settings.nlu_provider,
        nlu_model=settings.nlu_model,
        composer_provider=settings.composer_provider,
        composer_model=settings.composer_model,
        has_openai_key=bool(settings.openai_api_key),
    )
