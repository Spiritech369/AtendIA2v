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


class BaileysOutboundEchoBody(BaseModel):
    """Body for messages the operator sent from their own phone /
    WhatsApp Web — Baileys sees them via `fromMe=true` and forwards them
    here so AtendIA can mirror the conversation in the dashboard."""

    tenant_id: UUID
    to_phone: str = Field(min_length=8, max_length=24)
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
    """Full inbound pipeline for messages received via Baileys.

    Same contract as the Meta webhook: persist the message, emit the
    `MESSAGE_RECEIVED` event, evaluate workflow triggers, run the
    conversation turn (NLU + composer + outbound enqueue), and publish a
    realtime notification so the dashboard updates instantly.

    Idempotent on `(tenant_id, channel_message_id)`.
    """
    # Normalize phone to E.164 with leading '+' if missing
    phone = body.from_phone
    if not phone.startswith("+"):
        phone = "+" + phone

    cust_id = (
        await session.execute(
            text(
                "INSERT INTO customers (tenant_id, phone_e164) VALUES (:t, :p) "
                "ON CONFLICT (tenant_id, phone_e164) DO UPDATE "
                "SET phone_e164 = EXCLUDED.phone_e164 "
                "RETURNING id"
            ),
            {"t": body.tenant_id, "p": phone},
        )
    ).scalar()

    # Exclude soft-deleted conversations so an event after the operator
    # deleted the chat opens a fresh one instead of attaching to the
    # hidden tombstone.
    conv_id = (
        await session.execute(
            text(
                "SELECT id FROM conversations WHERE tenant_id = :t AND customer_id = :c "
                "AND deleted_at IS NULL "
                "ORDER BY last_activity_at DESC NULLS LAST LIMIT 1"
            ),
            {"t": body.tenant_id, "c": cust_id},
        )
    ).scalar()
    if conv_id is None:
        from atendia.state_machine.pipeline_loader import resolve_initial_stage

        initial_stage = await resolve_initial_stage(session, body.tenant_id)
        conv_id = (
            await session.execute(
                text(
                    "INSERT INTO conversations (tenant_id, customer_id, current_stage) "
                    "VALUES (:t, :c, :s) RETURNING id"
                ),
                {"t": body.tenant_id, "c": cust_id, "s": initial_stage},
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

    started_executions = await _run_inbound_pipeline(
        session=session,
        tenant_id=body.tenant_id,
        conversation_id=conv_id,
        channel_message_id=body.message_id,
        from_phone_e164=phone,
        text_body=body.text,
    )
    await session.commit()

    # Dispatch workflow executions outside the request transaction.
    if started_executions:
        from arq.connections import RedisSettings, create_pool

        from atendia.workflows.engine import enqueue_executions_to_workflows_queue

        try:
            arq_pool = await create_pool(
                RedisSettings.from_dsn(get_settings().redis_url)
            )
            try:
                await enqueue_executions_to_workflows_queue(
                    arq_pool, started_executions
                )
            finally:
                await arq_pool.aclose()
        except Exception:  # pragma: no cover
            pass

    return {
        "status": "ok",
        "conversation_id": str(conv_id),
        "message_id": str(inserted),
    }


async def _run_inbound_pipeline(
    *,
    session: AsyncSession,
    tenant_id: UUID,
    conversation_id,
    channel_message_id: str | None,
    from_phone_e164: str,
    text_body: str,
) -> list:
    """Event emission + workflow evaluation + runner turn + realtime publish.

    Returns the list of workflow execution IDs the caller should enqueue
    on the workflows queue after the request transaction commits.
    """
    from datetime import datetime as _dt
    from uuid import uuid4 as _uuid4

    from arq.connections import RedisSettings, create_pool
    from redis.asyncio import Redis as _Redis

    from atendia.contracts.event import EventType
    from atendia.contracts.message import (
        Message as CanonicalMessage,
    )
    from atendia.contracts.message import (
        MessageDirection,
    )
    from atendia.realtime.publisher import publish_event
    from atendia.runner.conversation_runner import ConversationRunner
    from atendia.state_machine.event_emitter import EventEmitter
    from atendia.webhooks.meta_routes import build_composer, build_nlu
    from atendia.workflows.engine import evaluate_event

    settings = get_settings()

    # 1. Emit MESSAGE_RECEIVED event so workflows + analytics see it.
    emitter = EventEmitter(session)
    event_row = await emitter.emit(
        conversation_id=conversation_id,
        tenant_id=tenant_id,
        event_type=EventType.MESSAGE_RECEIVED,
        payload={
            "channel_message_id": channel_message_id,
            "text": text_body,
        },
    )

    # 2. Evaluate workflow triggers in the same transaction. Execution IDs
    #    are returned so the caller can enqueue them after commit.
    started_executions = await evaluate_event(session, event_row.id)

    # 3. Live notification (best-effort).
    try:
        redis = _Redis.from_url(settings.redis_url)
        try:
            await publish_event(
                redis,
                tenant_id=str(tenant_id),
                conversation_id=str(conversation_id),
                event={
                    "type": "message_received",
                    "data": {
                        "channel_message_id": channel_message_id,
                        "text": text_body,
                        "conversation_id": str(conversation_id),
                    },
                },
            )
        finally:
            await redis.aclose()
    except Exception:  # pragma: no cover
        pass

    # 4. Run the conversation turn. The runner short-circuits on
    #    `bot_paused`, so if the operator already took control we just
    #    persist the inbound and stop here.
    next_turn = (
        await session.execute(
            text(
                "SELECT COALESCE(MAX(turn_number), 0) + 1 FROM turn_traces "
                "WHERE conversation_id = :c"
            ),
            {"c": conversation_id},
        )
    ).scalar()

    nlu = build_nlu(settings)
    composer = build_composer(settings)
    runner = ConversationRunner(session, nlu, composer)
    inbound_canonical = CanonicalMessage(
        id=str(_uuid4()),
        conversation_id=str(conversation_id),
        tenant_id=str(tenant_id),
        direction=MessageDirection.INBOUND,
        text=text_body,
        sent_at=_dt.now(UTC),
        attachments=[],
    )

    try:
        arq_pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    except Exception:  # pragma: no cover - worker unreachable, runner can't dispatch
        arq_pool = None

    try:
        try:
            await runner.run_turn(
                conversation_id=conversation_id,
                tenant_id=tenant_id,
                inbound=inbound_canonical,
                turn_number=next_turn,
                arq_pool=arq_pool,
                to_phone_e164=from_phone_e164,
            )
        except Exception:
            # Never crash the webhook — log via event and let Baileys retry-free.
            await emitter.emit(
                conversation_id=conversation_id,
                tenant_id=tenant_id,
                event_type=EventType.ERROR_OCCURRED,
                payload={
                    "where": "baileys_inbound_runner",
                    "message": "run_turn failed",
                },
            )
    finally:
        if arq_pool is not None:
            await arq_pool.aclose()

    return started_executions


@internal_router.post(
    "/outbound-echo", dependencies=[Depends(_validate_internal_token)]
)
async def baileys_outbound_echo(
    body: BaileysOutboundEchoBody,
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """Mirror a message the operator sent from their own phone.

    Baileys is a real WhatsApp Web client, so when the operator types
    from their phone the sidecar sees the event with `fromMe=true` and
    posts it here. We persist it as a `direction='outbound'` message so
    the dashboard reflects what's already on WhatsApp.

    We do NOT enqueue a `send_outbound` — the message has already been
    sent by the operator's own client; doubling it would deliver twice.
    """
    phone = body.to_phone
    if not phone.startswith("+"):
        phone = "+" + phone

    cust_id = (
        await session.execute(
            text(
                "INSERT INTO customers (tenant_id, phone_e164) VALUES (:t, :p) "
                "ON CONFLICT (tenant_id, phone_e164) DO UPDATE "
                "SET phone_e164 = EXCLUDED.phone_e164 "
                "RETURNING id"
            ),
            {"t": body.tenant_id, "p": phone},
        )
    ).scalar()

    # Exclude soft-deleted conversations so an event after the operator
    # deleted the chat opens a fresh one instead of attaching to the
    # hidden tombstone.
    conv_id = (
        await session.execute(
            text(
                "SELECT id FROM conversations WHERE tenant_id = :t AND customer_id = :c "
                "AND deleted_at IS NULL "
                "ORDER BY last_activity_at DESC NULLS LAST LIMIT 1"
            ),
            {"t": body.tenant_id, "c": cust_id},
        )
    ).scalar()
    if conv_id is None:
        from atendia.state_machine.pipeline_loader import resolve_initial_stage

        initial_stage = await resolve_initial_stage(session, body.tenant_id)
        conv_id = (
            await session.execute(
                text(
                    "INSERT INTO conversations (tenant_id, customer_id, current_stage) "
                    "VALUES (:t, :c, :s) RETURNING id"
                ),
                {"t": body.tenant_id, "c": cust_id, "s": initial_stage},
            )
        ).scalar()
        await session.execute(
            text("INSERT INTO conversation_state (conversation_id) VALUES (:c)"),
            {"c": conv_id},
        )

    # The operator just took control from their phone — pause the bot so
    # the runner doesn't reply on top of them.
    await session.execute(
        text(
            "UPDATE conversation_state SET bot_paused = TRUE "
            "WHERE conversation_id = :c"
        ),
        {"c": conv_id},
    )

    sent_at = datetime.fromtimestamp(body.ts / 1000, tz=UTC)
    inserted = (
        await session.execute(
            text(
                "INSERT INTO messages "
                "(conversation_id, tenant_id, direction, text, channel_message_id, "
                " sent_at, delivery_status, metadata_json) "
                "VALUES (:c, :t, 'outbound', :txt, :cmid, :ts, 'sent', "
                "        CAST(:meta AS JSONB)) "
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
                "meta": _json.dumps(
                    {"channel": "baileys", "source": "operator_device"}
                ),
            },
        )
    ).scalar_one_or_none()

    if inserted is None:
        await session.commit()
        return {"status": "duplicate"}

    await session.execute(
        text(
            "UPDATE conversations SET last_activity_at = :ts WHERE id = :c"
        ),
        {"ts": sent_at, "c": conv_id},
    )
    await session.commit()

    # Push to the dashboard.
    try:
        from redis.asyncio import Redis as _Redis

        from atendia.realtime.publisher import publish_event

        redis = _Redis.from_url(get_settings().redis_url)
        try:
            await publish_event(
                redis,
                tenant_id=str(body.tenant_id),
                conversation_id=str(conv_id),
                event={
                    "type": "message_sent",
                    "source": "operator_device",
                    "data": {
                        "channel_message_id": body.message_id,
                        "text": body.text,
                        "conversation_id": str(conv_id),
                        "status": "sent",
                    },
                },
            )
        finally:
            await redis.aclose()
    except Exception:  # pragma: no cover
        pass

    return {"status": "ok", "conversation_id": str(conv_id), "message_id": str(inserted)}
