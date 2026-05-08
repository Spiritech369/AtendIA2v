import json as _json
from datetime import UTC, datetime
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
from atendia.runner.composer_canned import CannedComposer
from atendia.runner.composer_openai import OpenAIComposer
from atendia.runner.composer_protocol import ComposerProvider
from atendia.runner.nlu_keywords import KeywordNLU
from atendia.runner.nlu_openai import OpenAINLU
from atendia.runner.nlu_protocol import NLUProvider
from atendia.webhooks.deduplication import is_duplicate

router = APIRouter()


def build_nlu(settings) -> NLUProvider:
    """Construct the NLU provider based on settings.nlu_provider.

    "keyword" -> in-memory keyword matcher (default fallback).
    "openai"  -> real LLM call via OpenAINLU. Requires openai_api_key.
    """
    if settings.nlu_provider == "openai":
        return OpenAINLU(
            api_key=settings.openai_api_key,
            model=settings.nlu_model,
            timeout_s=settings.nlu_timeout_s,
            retry_delays_ms=tuple(settings.nlu_retry_delays_ms),
        )
    return KeywordNLU()


def build_composer(settings) -> ComposerProvider:
    """Construct the Composer provider based on settings.composer_provider.

    "canned" -> CannedComposer (Phase 2 hardcoded text behavior, default fallback).
    "openai" -> OpenAIComposer (gpt-4o real LLM). Requires openai_api_key.
    """
    if settings.composer_provider == "openai":
        return OpenAIComposer(
            api_key=settings.openai_api_key,
            model=settings.composer_model,
            timeout_s=settings.composer_timeout_s,
            retry_delays_ms=tuple(settings.composer_retry_delays_ms),
        )
    return CannedComposer()


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


async def _resolve_attachment_urls(
    adapter: MetaCloudAPIAdapter,
    inbound_messages: list,
) -> None:
    """Populate InboundMessage.metadata.attachments[*].url via Meta Graph API.

    Best-effort: errors leave the URL as the empty string the parser already
    set, and the runner downstream skips Vision when url is empty. We do
    NOT raise — webhook contract is "always 200, retries are Meta's job".
    """
    from atendia.channels.base import InboundMessageMetadata
    for m in inbound_messages:
        if not m.metadata:
            continue
        meta = InboundMessageMetadata.model_validate(m.metadata)
        if not meta.attachments:
            continue
        for att in meta.attachments:
            if att.url:
                continue
            att.url = await adapter.fetch_media_url(att.media_id)
        m.metadata = meta.model_dump(mode="json")


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

    # Resolve any attachment URLs via the Meta Graph API before we persist
    # them. fetch_media_url returns "" on failure so a transient Meta hiccup
    # never 500s the webhook — the runner just skips Vision for that turn.
    await _resolve_attachment_urls(adapter, inbound_messages)

    redis = await _get_redis()
    received_count = 0
    try:
        # Record webhook arrival for channel status badge (Step 6).
        from datetime import datetime, timezone

        await redis.set(
            f"webhook:last_at:{tenant_id}",
            datetime.now(timezone.utc).isoformat(),
            ex=86400,  # expire after 24h of inactivity
        )
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
    metadata_json = _json.dumps(m.metadata or {})
    await session.execute(
        text(
            "INSERT INTO messages "
            "(conversation_id, tenant_id, direction, text, channel_message_id, "
            "sent_at, metadata_json) "
            "VALUES (:c, :t, 'inbound', :txt, :cmid, :ts, CAST(:meta AS JSONB))"
        ),
        {
            "c": conv_id,
            "t": tenant_id,
            "txt": m.text or "",
            "cmid": m.channel_message_id,
            "ts": datetime.now(UTC),
            "meta": metadata_json,
        },
    )

    # Bump unread count for the badge (scope gap: unread tracking)
    await session.execute(
        text("UPDATE conversations SET unread_count = unread_count + 1 WHERE id = :c"),
        {"c": conv_id},
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

    # Run conversation turn (T25): drives the state machine using the configured NLU.
    from datetime import datetime as _dt
    from uuid import uuid4 as _uuid4

    from atendia.channels.base import InboundMessageMetadata
    from atendia.contracts.message import (
        Attachment as CanonicalAttachment,
    )
    from atendia.contracts.message import (
        Message as CanonicalMessage,
    )
    from atendia.contracts.message import (
        MessageDirection,
    )
    from atendia.runner.conversation_runner import ConversationRunner

    # Find the next turn_number for this conversation
    next_turn = (await session.execute(
        text("SELECT COALESCE(MAX(turn_number), 0) + 1 FROM turn_traces "
             "WHERE conversation_id = :c"),
        {"c": conv_id},
    )).scalar()

    settings = get_settings()
    nlu = build_nlu(settings)
    composer = build_composer(settings)
    runner = ConversationRunner(session, nlu, composer)
    canonical_attachments: list[CanonicalAttachment] = []
    if m.metadata:
        meta = InboundMessageMetadata.model_validate(m.metadata)
        canonical_attachments = [
            CanonicalAttachment(
                media_id=a.media_id, mime_type=a.mime_type,
                url=a.url, caption=a.caption,
            )
            for a in meta.attachments
        ]
    inbound_canonical = CanonicalMessage(
        id=str(_uuid4()),
        conversation_id=str(conv_id),
        tenant_id=str(tenant_id),
        direction=MessageDirection.INBOUND,
        text=m.text or "",
        sent_at=_dt.now(UTC),
        attachments=canonical_attachments,
    )

    # Build an arq pool so the runner can enqueue outbound messages.
    from arq.connections import RedisSettings, create_pool
    arq_pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    try:
        trace = await runner.run_turn(
            conversation_id=conv_id,
            tenant_id=tenant_id,
            inbound=inbound_canonical,
            turn_number=next_turn,
            arq_pool=arq_pool,
            to_phone_e164=m.from_phone_e164,
        )
        _ = trace  # silence unused-trace lint
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
    finally:
        await arq_pool.aclose()


async def _update_status(session: AsyncSession, r) -> None:
    """Update messages.delivery_status by channel_message_id (no-op if not found)."""
    await session.execute(
        text("UPDATE messages SET delivery_status = :s WHERE channel_message_id = :cm"),
        {"s": r.status, "cm": r.channel_message_id},
    )
