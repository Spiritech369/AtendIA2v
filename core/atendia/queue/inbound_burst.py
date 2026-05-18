from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from arq.connections import RedisSettings, create_pool
from arq.worker import Retry
from redis.asyncio import Redis as AsyncRedis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from atendia.channels.base import InboundMessageMetadata
from atendia.config import get_settings
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
from atendia.webhooks.meta_routes import build_composer, build_nlu

BURST_DEFER_SECONDS = 5
BURST_MARKER_TTL_SECONDS = 120
RUNNER_LOCK_TTL_SECONDS = 90


def _burst_key(tenant_id: str, conversation_id: str) -> str:
    return f"inbound:burst:{tenant_id}:{conversation_id}:latest"


def _runner_lock_key(tenant_id: str, conversation_id: str) -> str:
    return f"inbound:runner-lock:{tenant_id}:{conversation_id}"


def _redis_value(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return str(value)


async def enqueue_inbound_burst(
    redis,
    *,
    tenant_id: UUID,
    conversation_id: UUID,
    latest_message_id: UUID,
    from_phone_e164: str,
) -> None:
    tenant = str(tenant_id)
    conversation = str(conversation_id)
    latest = str(latest_message_id)
    await redis.set(
        _burst_key(tenant, conversation),
        latest,
        ex=BURST_MARKER_TTL_SECONDS,
    )
    await redis.enqueue_job(
        "process_inbound_burst",
        tenant,
        conversation,
        latest,
        from_phone_e164,
        _defer_by=BURST_DEFER_SECONDS,
        _job_id=f"inbound-burst:{tenant}:{conversation}:{latest}",
    )


def _attachment_list(metadata: dict[str, Any]) -> list[CanonicalAttachment]:
    meta = InboundMessageMetadata.model_validate(metadata)
    return [
        CanonicalAttachment(
            media_id=attachment.media_id,
            mime_type=attachment.mime_type,
            url=attachment.url,
            caption=attachment.caption,
        )
        for attachment in meta.attachments
    ]


def _decode_metadata(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value:
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return decoded if isinstance(decoded, dict) else {}
    return {}


def _join_burst_text(rows: list[dict[str, Any]]) -> str:
    parts = [str(row.get("text") or "").strip() for row in rows]
    return "\n".join(part for part in parts if part)


async def process_inbound_burst(
    ctx: dict,
    tenant_id: str,
    conversation_id: str,
    latest_message_id: str,
    from_phone_e164: str,
) -> dict:
    redis = ctx.get("redis")
    redis_owned = False
    settings = get_settings()
    if redis is None:
        redis = AsyncRedis.from_url(settings.redis_url)
        redis_owned = True

    marker_key = _burst_key(tenant_id, conversation_id)
    latest_marker = _redis_value(await redis.get(marker_key))
    if latest_marker != latest_message_id:
        if redis_owned:
            await redis.aclose()
        return {"status": "stale"}

    lock_key = _runner_lock_key(tenant_id, conversation_id)
    lock_token = uuid4().hex
    locked = await redis.set(lock_key, lock_token, ex=RUNNER_LOCK_TTL_SECONDS, nx=True)
    if not locked:
        if redis_owned:
            await redis.aclose()
        raise Retry(defer=3)

    engine = ctx.get("engine") or create_async_engine(settings.database_url)
    arq_pool = ctx.get("arq_pool")
    arq_pool_owned = False
    if arq_pool is None:
        arq_pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
        arq_pool_owned = True
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            latest_marker = _redis_value(await redis.get(marker_key))
            if latest_marker != latest_message_id:
                return {"status": "stale"}

            last_outbound_at = (
                await session.execute(
                    text(
                        "SELECT MAX(sent_at) FROM messages "
                        "WHERE tenant_id = :tenant_id "
                        "AND conversation_id = :conversation_id "
                        "AND direction = 'outbound'"
                    ),
                    {"tenant_id": tenant_id, "conversation_id": conversation_id},
                )
            ).scalar()
            rows = (
                (
                    await session.execute(
                        text(
                            "SELECT id, text, channel_message_id, sent_at, metadata_json "
                            "FROM messages "
                            "WHERE tenant_id = :tenant_id "
                            "AND conversation_id = :conversation_id "
                            "AND direction = 'inbound' "
                            "AND (CAST(:last_outbound_at AS TIMESTAMPTZ) IS NULL "
                            "OR sent_at > CAST(:last_outbound_at AS TIMESTAMPTZ)) "
                            "ORDER BY sent_at ASC, id ASC"
                        ),
                        {
                            "tenant_id": tenant_id,
                            "conversation_id": conversation_id,
                            "last_outbound_at": last_outbound_at,
                        },
                    )
                )
                .mappings()
                .all()
            )
            if not rows:
                return {"status": "empty"}

            batch_rows = [dict(row) for row in rows]
            latest_row = batch_rows[-1]
            latest_metadata = _decode_metadata(latest_row.get("metadata_json"))
            from atendia.api.message_attachments import load_runner_attachments

            attachments = await load_runner_attachments(session, message_id=latest_row["id"])
            if not attachments:
                attachments = _attachment_list(latest_metadata)
            batch_message_ids = [str(row["id"]) for row in batch_rows]
            batch_channel_ids = [
                str(row["channel_message_id"])
                for row in batch_rows
                if row.get("channel_message_id")
            ]
            inbound = CanonicalMessage(
                id=str(uuid4()),
                conversation_id=conversation_id,
                tenant_id=tenant_id,
                direction=MessageDirection.INBOUND,
                text=_join_burst_text(batch_rows),
                channel_message_id=latest_row.get("channel_message_id"),
                sent_at=latest_row.get("sent_at") or datetime.now(UTC),
                metadata={
                    **latest_metadata,
                    "batch_message_ids": batch_message_ids,
                    "batch_channel_message_ids": batch_channel_ids,
                    "batch_size": len(batch_rows),
                },
                attachments=attachments,
            )

            next_turn = (
                await session.execute(
                    text(
                        "SELECT COALESCE(MAX(turn_number), 0) + 1 FROM turn_traces "
                        "WHERE conversation_id = :conversation_id"
                    ),
                    {"conversation_id": conversation_id},
                )
            ).scalar()
            runner = ConversationRunner(session, build_nlu(settings), build_composer(settings))
            try:
                await runner.run_turn(
                    conversation_id=UUID(conversation_id),
                    tenant_id=UUID(tenant_id),
                    inbound=inbound,
                    turn_number=next_turn,
                    arq_pool=arq_pool,
                    to_phone_e164=from_phone_e164,
                )
                await session.commit()
            except Exception:
                from atendia.contracts.event import EventType
                from atendia.state_machine.event_emitter import EventEmitter

                emitter = EventEmitter(session)
                await emitter.emit(
                    conversation_id=UUID(conversation_id),
                    tenant_id=UUID(tenant_id),
                    event_type=EventType.ERROR_OCCURRED,
                    payload={"where": "conversation_runner", "message": "run_turn failed"},
                )
                await session.commit()
                return {"status": "failed"}

            return {"status": "processed", "batch_size": len(batch_rows)}
    finally:
        current_lock = _redis_value(await redis.get(lock_key))
        if current_lock == lock_token:
            await redis.delete(lock_key)
        if arq_pool_owned:
            await arq_pool.aclose()
        if "engine" not in ctx:
            await engine.dispose()
        if redis_owned:
            await redis.aclose()
