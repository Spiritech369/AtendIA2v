"""Baileys WhatsApp channel — tenant-scoped HTTP routes.

Two routers:
* `integrations_router` (public, mounted at `/api/v1/integrations/baileys`)
  for the frontend to manage the connection lifecycle.
* `internal_router` (mounted at `/api/v1/internal/baileys`) that the
  sidecar calls back into when a WhatsApp message arrives.

The internal route validates `X-Internal-Token` against the shared
secret and short-circuits FastAPI's normal auth deps.

Design: `docs/plans/2026-05-13-baileys-integration-design.md`.
"""
from __future__ import annotations

import json as _json
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.api._auth_helpers import AuthUser
from atendia.api._deps import current_tenant_id, current_user, require_tenant_admin
from atendia.config import get_settings
from atendia.db.models.tenant_baileys_config import TenantBaileysConfig
from atendia.db.session import get_db_session
from atendia.integrations import baileys_client

integrations_router = APIRouter()
internal_router = APIRouter()


# ── Public / tenant-scoped endpoints ───────────────────────────────────────


class BaileysStatusResponse(BaseModel):
    status: str
    phone: str | None
    last_status_at: str
    reason: str | None
    prefer_over_meta: bool


class PreferenceBody(BaseModel):
    prefer_over_meta: bool


class TestSendBody(BaseModel):
    to_phone: str = Field(min_length=8, max_length=24)
    text: str = Field(min_length=1, max_length=2000)


async def _upsert_config(
    session: AsyncSession,
    tenant_id: UUID,
    *,
    status_val: str,
    phone: str | None,
    enabled: bool | None = None,
) -> TenantBaileysConfig:
    """UPSERT tenant_baileys_config from sidecar status."""
    stmt = pg_insert(TenantBaileysConfig).values(
        tenant_id=tenant_id,
        enabled=enabled if enabled is not None else (status_val == "connected"),
        connected_phone=phone,
        last_status=status_val,
        last_status_at=datetime.now(UTC),
    )
    set_values = {
        "connected_phone": phone,
        "last_status": status_val,
        "last_status_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    }
    if enabled is not None:
        set_values["enabled"] = enabled
    stmt = stmt.on_conflict_do_update(index_elements=["tenant_id"], set_=set_values)
    await session.execute(stmt)
    await session.commit()
    row = (
        await session.execute(
            text("SELECT * FROM tenant_baileys_config WHERE tenant_id = :t"),
            {"t": tenant_id},
        )
    ).mappings().one()
    return row  # type: ignore[return-value]


@integrations_router.get("/status", response_model=BaileysStatusResponse)
async def get_baileys_status(
    user: AuthUser = Depends(current_user),  # noqa: ARG001
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> BaileysStatusResponse:
    try:
        live = await baileys_client.get_status(tenant_id)
    except baileys_client.BaileysBridgeUnavailable as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"sidecar: {exc}") from exc
    row = await _upsert_config(
        session, tenant_id, status_val=live.status, phone=live.phone
    )
    return BaileysStatusResponse(
        status=live.status,
        phone=live.phone,
        last_status_at=live.last_status_at,
        reason=live.reason,
        prefer_over_meta=bool(row["prefer_over_meta"]),
    )


@integrations_router.post("/connect", response_model=BaileysStatusResponse)
async def baileys_connect(
    user: AuthUser = Depends(require_tenant_admin),  # noqa: ARG001
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> BaileysStatusResponse:
    try:
        live = await baileys_client.start_session(tenant_id)
    except baileys_client.BaileysBridgeUnavailable as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"sidecar: {exc}") from exc
    row = await _upsert_config(
        session, tenant_id, status_val=live.status, phone=live.phone, enabled=True
    )
    return BaileysStatusResponse(
        status=live.status,
        phone=live.phone,
        last_status_at=live.last_status_at,
        reason=live.reason,
        prefer_over_meta=bool(row["prefer_over_meta"]),
    )


@integrations_router.post("/disconnect", response_model=BaileysStatusResponse)
async def baileys_disconnect(
    user: AuthUser = Depends(require_tenant_admin),  # noqa: ARG001
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> BaileysStatusResponse:
    try:
        live = await baileys_client.stop_session(tenant_id)
    except baileys_client.BaileysBridgeUnavailable as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"sidecar: {exc}") from exc
    row = await _upsert_config(
        session, tenant_id, status_val=live.status, phone=None, enabled=False
    )
    return BaileysStatusResponse(
        status=live.status,
        phone=None,
        last_status_at=live.last_status_at,
        reason=live.reason,
        prefer_over_meta=bool(row["prefer_over_meta"]),
    )


@integrations_router.get("/qr")
async def baileys_qr(
    user: AuthUser = Depends(current_user),  # noqa: ARG001
    tenant_id: UUID = Depends(current_tenant_id),
) -> dict:
    """Returns `{qr: 'data:image/png;base64,...'}` when scan is pending."""
    try:
        qr = await baileys_client.get_qr(tenant_id)
    except baileys_client.BaileysBridgeUnavailable as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"sidecar: {exc}") from exc
    return {"qr": qr}


@integrations_router.patch("/preference", response_model=BaileysStatusResponse)
async def update_baileys_preference(
    body: PreferenceBody,
    user: AuthUser = Depends(require_tenant_admin),  # noqa: ARG001
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> BaileysStatusResponse:
    await session.execute(
        text(
            "UPDATE tenant_baileys_config SET prefer_over_meta = :p, updated_at = now() "
            "WHERE tenant_id = :t"
        ),
        {"p": body.prefer_over_meta, "t": tenant_id},
    )
    await session.commit()
    return await get_baileys_status(  # type: ignore[return-value]
        tenant_id=tenant_id, user=None, session=session  # noqa
    )


@integrations_router.post("/test-send")
async def baileys_test_send(
    body: TestSendBody,
    user: AuthUser = Depends(require_tenant_admin),  # noqa: ARG001
    tenant_id: UUID = Depends(current_tenant_id),
) -> dict:
    try:
        result = await baileys_client.send_text(tenant_id, body.to_phone, body.text)
    except baileys_client.BaileysBridgeUnavailable as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"sidecar: {exc}") from exc
    return {"message_id": result.message_id, "sent_at": result.sent_at}


# ── Internal webhook (sidecar → backend) ───────────────────────────────────


class BaileysInboundBody(BaseModel):
    tenant_id: UUID
    from_phone: str = Field(min_length=8, max_length=24)
    text: str
    ts: int
    message_id: str | None = None


async def _validate_internal_token(
    x_internal_token: str | None = Header(default=None, alias="X-Internal-Token"),
) -> None:
    settings = get_settings()
    expected = settings.baileys_internal_token
    if not expected or x_internal_token != expected:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "invalid internal token")


@internal_router.post("/inbound", dependencies=[Depends(_validate_internal_token)])
async def baileys_inbound(
    body: BaileysInboundBody,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """Persist an inbound message + run conversation turn.

    Mirrors meta_routes._persist_inbound (the meaningful subset for v1):
    find/create customer + conversation, INSERT message, run turn. Skips
    Event/Workflow/Publish wiring — Phase 2 work, tracked in design doc.
    """
    # Normalize phone to E.164 with leading '+' if missing
    phone = body.from_phone
    if not phone.startswith("+"):
        phone = "+" + phone

    cust_id = (
        await session.execute(
            text(
                "INSERT INTO customers (tenant_id, phone_e164) VALUES (:t, :p) "
                "ON CONFLICT (tenant_id, phone_e164) DO UPDATE SET phone_e164 = EXCLUDED.phone_e164 "
                "RETURNING id"
            ),
            {"t": body.tenant_id, "p": phone},
        )
    ).scalar()

    conv_id = (
        await session.execute(
            text(
                "SELECT id FROM conversations WHERE tenant_id = :t AND customer_id = :c "
                "ORDER BY last_activity_at DESC NULLS LAST LIMIT 1"
            ),
            {"t": body.tenant_id, "c": cust_id},
        )
    ).scalar()
    if conv_id is None:
        conv_id = (
            await session.execute(
                text(
                    "INSERT INTO conversations (tenant_id, customer_id) VALUES (:t, :c) "
                    "RETURNING id"
                ),
                {"t": body.tenant_id, "c": cust_id},
            )
        ).scalar()
        await session.execute(
            text("INSERT INTO conversation_state (conversation_id) VALUES (:c)"),
            {"c": conv_id},
        )

    sent_at = datetime.fromtimestamp(body.ts / 1000, tz=UTC)
    inserted = (
        await session.execute(
            text(
                "INSERT INTO messages "
                "(conversation_id, tenant_id, direction, text, channel_message_id, "
                " sent_at, metadata_json) "
                "VALUES (:c, :t, 'inbound', :txt, :cmid, :ts, CAST(:meta AS JSONB)) "
                "ON CONFLICT (tenant_id, channel_message_id) "
                "WHERE channel_message_id IS NOT NULL DO NOTHING "
                "RETURNING id"
            ),
            {
                "c": conv_id,
                "t": body.tenant_id,
                "txt": body.text,
                "cmid": body.message_id,
                "ts": sent_at,
                "meta": _json.dumps({"channel": "baileys"}),
            },
        )
    ).scalar_one_or_none()

    if inserted is None:
        # Duplicate webhook (sidecar retried). Already persisted.
        await session.commit()
        return {"status": "duplicate"}

    await session.execute(
        text("UPDATE conversations SET unread_count = unread_count + 1 WHERE id = :c"),
        {"c": conv_id},
    )
    await session.commit()
    return {"status": "ok", "conversation_id": str(conv_id), "message_id": str(inserted)}
