"""Channel status endpoint — WhatsApp connection + circuit breaker (Step 6).

Returns a combined status object so the frontend can render a live badge
in the AppShell header:
- `whatsapp_status`: connected | inactive | paused
- `circuit_breaker_open`: bool
- `last_webhook_at`: ISO timestamp or null
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from redis.asyncio import Redis

from atendia.api._auth_helpers import AuthUser
from atendia.api._deps import current_tenant_id, current_user
from atendia.config import get_settings
from atendia.queue.circuit_breaker import is_open

router = APIRouter()

STALE_THRESHOLD_SECONDS = 300  # 5 minutes without webhooks → "inactive"


class ChannelStatusResponse(BaseModel):
    whatsapp_status: str  # "connected" | "inactive" | "paused"
    circuit_breaker_open: bool
    last_webhook_at: datetime | None


@router.get("", response_model=ChannelStatusResponse)
async def get_channel_status(
    user: AuthUser = Depends(current_user),  # noqa: ARG001
    tenant_id: UUID = Depends(current_tenant_id),
) -> ChannelStatusResponse:
    redis = Redis.from_url(get_settings().redis_url)
    try:
        cb_open = await is_open(redis, str(tenant_id))
        raw_ts = await redis.get(f"webhook:last_at:{tenant_id}")
    finally:
        await redis.aclose()

    last_webhook_at: datetime | None = None
    if raw_ts:
        last_webhook_at = datetime.fromisoformat(raw_ts.decode())

    # Determine status
    if cb_open:
        wa_status = "paused"
    elif last_webhook_at is None:
        wa_status = "inactive"
    else:
        age = (datetime.now(timezone.utc) - last_webhook_at).total_seconds()
        wa_status = "connected" if age < STALE_THRESHOLD_SECONDS else "inactive"

    return ChannelStatusResponse(
        whatsapp_status=wa_status,
        circuit_breaker_open=cb_open,
        last_webhook_at=last_webhook_at,
    )
