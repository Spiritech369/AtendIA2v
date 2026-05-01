import json as _json
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import PlainTextResponse
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.channels.meta_cloud_api import MetaCloudAPIAdapter
from atendia.channels.tenant_config import (
    MetaTenantConfigNotFoundError,
    load_meta_config,
)
from atendia.config import get_settings
from atendia.db.session import get_db_session
from atendia.webhooks.deduplication import is_duplicate

router = APIRouter()


@router.get("/webhooks/meta/{tenant_id}", response_class=PlainTextResponse)
async def verify_subscription(
    tenant_id: UUID,
    hub_mode: str = Query("", alias="hub.mode"),
    hub_challenge: str = Query("", alias="hub.challenge"),
    hub_verify_token: str = Query("", alias="hub.verify_token"),
    session: AsyncSession = Depends(get_db_session),
) -> str:
    if hub_mode != "subscribe":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="invalid hub.mode",
        )
    try:
        cfg = await load_meta_config(session, tenant_id)
    except MetaTenantConfigNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="tenant has no Meta config",
        )
    if hub_verify_token != cfg.verify_token:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="verify_token mismatch",
        )
    return hub_challenge


async def _get_redis() -> Redis:
    return Redis.from_url(get_settings().redis_url)


@router.post("/webhooks/meta/{tenant_id}")
async def receive_inbound(
    tenant_id: UUID,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    body = await request.body()
    signature = request.headers.get("x-hub-signature-256", "")

    settings = get_settings()
    adapter = MetaCloudAPIAdapter(
        access_token=settings.meta_access_token,
        app_secret=settings.meta_app_secret,
        api_version=settings.meta_api_version,
        base_url=settings.meta_base_url,
    )
    if not adapter.validate_signature(body, signature):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="invalid signature"
        )

    try:
        payload = _json.loads(body)
    except _json.JSONDecodeError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="invalid json"
        )

    inbound_messages = adapter.parse_webhook(payload, tenant_id=str(tenant_id))
    statuses = adapter.parse_status_callback(payload)

    redis = await _get_redis()
    received_count = 0
    try:
        for m in inbound_messages:
            if await is_duplicate(redis, m.channel_message_id):
                continue
            await _persist_inbound(session, tenant_id, m)
            received_count += 1
        for r in statuses:
            await _update_status(session, r)
        await session.commit()
    finally:
        await redis.aclose()

    return {
        "status": "ok",
        "received": received_count,
        "statuses": len(statuses),
    }


async def _persist_inbound(session: AsyncSession, tenant_id: UUID, m) -> None:
    """Find or create customer + conversation, then insert inbound message."""
    cust_id = (await session.execute(
        text(
            "INSERT INTO customers (tenant_id, phone_e164) VALUES (:t, :p) "
            "ON CONFLICT (tenant_id, phone_e164) DO UPDATE SET phone_e164 = EXCLUDED.phone_e164 "
            "RETURNING id"
        ),
        {"t": tenant_id, "p": m.from_phone_e164},
    )).scalar()
    conv_id = (await session.execute(
        text(
            "SELECT id FROM conversations WHERE tenant_id = :t AND customer_id = :c "
            "ORDER BY last_activity_at DESC LIMIT 1"
        ),
        {"t": tenant_id, "c": cust_id},
    )).scalar()
    if conv_id is None:
        conv_id = (await session.execute(
            text(
                "INSERT INTO conversations (tenant_id, customer_id) VALUES (:t, :c) "
                "RETURNING id"
            ),
            {"t": tenant_id, "c": cust_id},
        )).scalar()
        await session.execute(
            text("INSERT INTO conversation_state (conversation_id) VALUES (:c)"),
            {"c": conv_id},
        )
    await session.execute(
        text(
            "INSERT INTO messages "
            "(conversation_id, tenant_id, direction, text, channel_message_id, "
            "sent_at, metadata_json) "
            "VALUES (:c, :t, 'inbound', :txt, :cmid, :ts, '{}'::jsonb)"
        ),
        {
            "c": conv_id,
            "t": tenant_id,
            "txt": m.text or "",
            "cmid": m.channel_message_id,
            "ts": datetime.now(timezone.utc),
        },
    )

    # Emit event (T15)
    from atendia.contracts.event import EventType
    from atendia.state_machine.event_emitter import EventEmitter
    emitter = EventEmitter(session)
    await emitter.emit(
        conversation_id=conv_id,
        tenant_id=tenant_id,
        event_type=EventType.MESSAGE_RECEIVED,
        payload={
            "channel_message_id": m.channel_message_id,
            "text": m.text or "",
        },
    )

    # Publish to Pub/Sub for realtime subscribers (T22)
    from atendia.realtime.publisher import publish_event
    redis_client = await _get_redis()
    try:
        await publish_event(
            redis_client,
            tenant_id=str(tenant_id),
            conversation_id=str(conv_id),
            event={
                "type": "message_received",
                "data": {
                    "channel_message_id": m.channel_message_id,
                    "text": m.text or "",
                    "conversation_id": str(conv_id),
                },
            },
        )
    finally:
        await redis_client.aclose()

    # Run conversation turn (T25): drives the state machine using KeywordNLU.
    from atendia.runner.conversation_runner import ConversationRunner
    from atendia.runner.nlu_keywords import KeywordNLU
    from atendia.contracts.message import Message as CanonicalMessage, MessageDirection
    from datetime import datetime as _dt, timezone as _tz
    from uuid import uuid4 as _uuid4

    # Find the next turn_number for this conversation
    next_turn = (await session.execute(
        text("SELECT COALESCE(MAX(turn_number), 0) + 1 FROM turn_traces "
             "WHERE conversation_id = :c"),
        {"c": conv_id},
    )).scalar()

    nlu = KeywordNLU()
    nlu.feed(m.text or "")
    runner = ConversationRunner(session, nlu)
    inbound_canonical = CanonicalMessage(
        id=str(_uuid4()),
        conversation_id=str(conv_id),
        tenant_id=str(tenant_id),
        direction=MessageDirection.INBOUND,
        text=m.text or "",
        sent_at=_dt.now(_tz.utc),
    )
    try:
        trace = await runner.run_turn(
            conversation_id=conv_id,
            tenant_id=tenant_id,
            inbound=inbound_canonical,
            turn_number=next_turn,
        )
        # Dispatch outbound (T26)
        from atendia.runner.outbound_dispatcher import dispatch as dispatch_outbound
        from arq.connections import RedisSettings, create_pool
        # Build a fresh arq pool per request — small overhead, simple lifecycle.
        arq_pool = await create_pool(RedisSettings.from_dsn(get_settings().redis_url))
        try:
            from atendia.state_machine.action_resolver import resolve_action
            from atendia.contracts.nlu_result import Intent
            from atendia.state_machine.pipeline_loader import load_active_pipeline
            pipeline = await load_active_pipeline(session, tenant_id)
            target_stage_id = trace.state_after["current_stage"]
            target_stage = next(s for s in pipeline.stages if s.id == target_stage_id)
            try:
                action = resolve_action(
                    target_stage,
                    Intent(trace.state_after.get("last_intent") or "greeting"),
                )
            except Exception:
                action = "ask_clarification"
            await dispatch_outbound(
                arq_pool,
                action=action,
                tenant_id=tenant_id,
                to_phone_e164=m.from_phone_e164,
                conversation_id=conv_id,
            )
        finally:
            await arq_pool.aclose()
    except Exception:
        # Don't crash the webhook handler if the runner fails — just log via event.
        # In production this would also bubble to monitoring.
        from atendia.contracts.event import EventType
        await emitter.emit(
            conversation_id=conv_id,
            tenant_id=tenant_id,
            event_type=EventType.ERROR_OCCURRED,
            payload={"where": "conversation_runner", "message": "run_turn failed"},
        )


async def _update_status(session: AsyncSession, r) -> None:
    """Update messages.delivery_status by channel_message_id (no-op if not found)."""
    await session.execute(
        text("UPDATE messages SET delivery_status = :s WHERE channel_message_id = :cm"),
        {"s": r.status, "cm": r.channel_message_id},
    )
