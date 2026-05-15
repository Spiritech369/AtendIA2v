"""Channel status endpoint — Meta + Baileys connection state.

Returns a combined status object so the operator badge in the sidebar
can render "WhatsApp (Meta) connected" / "WhatsApp (Baileys) pairing" /
"WA pausado" etc.

Legacy shape (`whatsapp_status` / `circuit_breaker_open` /
`last_webhook_at`) is preserved for backward compatibility with the
existing frontend badge. New fields (`active_channel` + `channels`)
expose per-channel detail so the badge can name which transport is
serving the tenant right now.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.api._auth_helpers import AuthUser
from atendia.api._deps import current_tenant_id, current_user
from atendia.config import get_settings
from atendia.db.models.tenant_baileys_config import TenantBaileysConfig
from atendia.db.session import get_db_session
from atendia.queue.circuit_breaker import is_open

router = APIRouter()

STALE_THRESHOLD_SECONDS = 300  # 5 minutes without webhooks → "inactive"


class ChannelDetail(BaseModel):
    """Per-channel status snapshot. `phone` is baileys-only."""

    status: str  # connected | inactive | disconnected | pairing | error | paused | not_configured
    last_seen_at: datetime | None = None
    phone: str | None = None


class ChannelStatusResponse(BaseModel):
    # ── Legacy fields (kept for backward compat with the existing badge) ──
    whatsapp_status: str  # "connected" | "inactive" | "paused"
    circuit_breaker_open: bool
    last_webhook_at: datetime | None
    # ── New: per-channel detail + which channel is currently active ──
    active_channel: str  # "meta" | "baileys"
    channels: dict[str, ChannelDetail]


# Baileys reports a small enum on `tenant_baileys_config.last_status`.
# We translate it to the same friendly vocabulary the badge already uses
# for Meta so the frontend only has to know one set of states.
_BAILEYS_STATUS_MAP = {
    "connected": "connected",
    "qr_pending": "pairing",
    "connecting": "pairing",
    "disconnected": "disconnected",
    "error": "error",
}


def _derive_meta_status(cb_open: bool, last_webhook_at: datetime | None, now: datetime) -> str:
    if cb_open:
        return "paused"
    if last_webhook_at is None:
        return "inactive"
    age = (now - last_webhook_at).total_seconds()
    return "connected" if age < STALE_THRESHOLD_SECONDS else "inactive"


def _pick_active_channel(
    *,
    bc: TenantBaileysConfig | None,
    meta_status: str,
    baileys_status: str,
) -> str:
    """Operator-controlled preference wins; otherwise prefer whichever
    transport is actually serving traffic right now."""
    if bc is None or not bc.enabled:
        return "meta"
    if bc.prefer_over_meta:
        return "baileys"
    # Baileys is configured but not preferred — fall over to it only
    # when it's healthy AND Meta isn't.
    if baileys_status == "connected" and meta_status != "connected":
        return "baileys"
    return "meta"


def _legacy_status(active: str, meta_status: str, baileys_status: str) -> str:
    """Map the active channel's status into the original 3-state vocabulary
    (connected / inactive / paused) so the existing badge keeps working
    without code changes."""
    if active == "meta":
        return meta_status
    # Baileys active — only "connected" maps cleanly; anything else (pairing,
    # disconnected, error) collapses to "inactive" since "paused" is a
    # Meta-only concept (circuit breaker).
    return "connected" if baileys_status == "connected" else "inactive"


@router.get("", response_model=ChannelStatusResponse)
async def get_channel_status(
    user: AuthUser = Depends(current_user),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
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

    now = datetime.now(timezone.utc)
    meta_status = _derive_meta_status(cb_open, last_webhook_at, now)

    bc = (
        await session.execute(
            select(TenantBaileysConfig).where(TenantBaileysConfig.tenant_id == tenant_id)
        )
    ).scalar_one_or_none()

    if bc is None or not bc.enabled:
        baileys_detail = ChannelDetail(status="not_configured")
        baileys_status = "not_configured"
    else:
        baileys_status = _BAILEYS_STATUS_MAP.get(bc.last_status, "disconnected")
        baileys_detail = ChannelDetail(
            status=baileys_status,
            last_seen_at=bc.last_status_at,
            phone=bc.connected_phone,
        )

    meta_detail = ChannelDetail(status=meta_status, last_seen_at=last_webhook_at)
    active = _pick_active_channel(bc=bc, meta_status=meta_status, baileys_status=baileys_status)

    return ChannelStatusResponse(
        whatsapp_status=_legacy_status(active, meta_status, baileys_status),
        circuit_breaker_open=cb_open,
        last_webhook_at=last_webhook_at,
        active_channel=active,
        channels={"meta": meta_detail, "baileys": baileys_detail},
    )
