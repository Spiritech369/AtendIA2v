from datetime import UTC, datetime
from typing import ClassVar
from uuid import UUID, uuid4

from arq.connections import RedisSettings
from arq.worker import Retry
from redis.asyncio import Redis as AsyncRedis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from atendia.channels.base import OutboundMessage
from atendia.channels.meta_cloud_api import MetaCloudAPIAdapter
from atendia.channels.tenant_config import load_meta_config
from atendia.config import get_settings
from atendia.queue.circuit_breaker import (
    OPEN_DURATION_SECONDS,
    is_open,
    record_failure,
    record_success,
)
from atendia.queue.force_summary_job import force_summary
from atendia.queue.index_document_job import index_document
from atendia.queue.workflow_jobs import execute_workflow_step, poll_workflow_triggers


def _is_transient(err: str | None) -> bool:
    """Returns True if the error string indicates a transient failure that should be retried."""
    if not err:
        return False
    if "transport_error" in err:
        return True
    # meta_error_5xx (e.g. meta_error_503)
    if "meta_error_5" in err:
        return True
    return False


async def _get_redis_from_ctx(ctx: dict) -> tuple[object, bool]:
    """Returns (redis, owned_locally).
    If ctx has a 'redis' key (provided by arq), use it; we do NOT close it.
    Otherwise create one and return owned=True so caller can close it.
    """
    if "redis" in ctx and ctx["redis"] is not None:
        return ctx["redis"], False
    client = AsyncRedis.from_url(get_settings().redis_url)
    return client, True


async def send_outbound(ctx: dict, msg_dict: dict) -> dict:
    """arq worker function. Sends an outbound message via Meta and persists it."""
    msg = OutboundMessage.model_validate(msg_dict)
    settings = get_settings()

    # Circuit breaker (T20) — defer if open
    redis, redis_owned = await _get_redis_from_ctx(ctx)
    try:
        if await is_open(redis, msg.tenant_id):
            raise Retry(defer=OPEN_DURATION_SECONDS)
    except Retry:
        if redis_owned:
            await redis.aclose()
        raise

    engine = ctx.get("engine") or create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    try:
        async with session_factory() as session:
            cfg = await load_meta_config(session, UUID(msg.tenant_id))
            adapter = MetaCloudAPIAdapter(
                access_token=settings.meta_access_token,
                app_secret=settings.meta_app_secret,
                api_version=settings.meta_api_version,
                base_url=settings.meta_base_url,
            )
            message_id = str(uuid4())
            receipt = await adapter.send(
                msg, phone_number_id=cfg.phone_number_id, message_id=message_id,
            )

            # Update breaker state from receipt (T20)
            if receipt.status == "sent":
                await record_success(redis, msg.tenant_id)
            elif receipt.status == "failed":
                await record_failure(redis, msg.tenant_id)

            # Retry transient failures with exponential backoff (T18)
            if receipt.status == "failed" and _is_transient(receipt.error):
                job_try = ctx.get("job_try", 1)
                if job_try < 4:
                    raise Retry(defer=2 ** job_try)

            await _persist_outbound(session, msg, message_id, receipt)

            # Publish to Pub/Sub for realtime subscribers (T22)
            from atendia.realtime.publisher import publish_event
            # Look up conversation_id we just persisted
            conv_id = (await session.execute(
                text("SELECT conversation_id FROM messages WHERE id = :id"),
                {"id": message_id},
            )).scalar()
            await publish_event(
                redis,
                tenant_id=msg.tenant_id,
                conversation_id=str(conv_id),
                event={
                    "type": "message_sent",
                    "data": {
                        "channel_message_id": receipt.channel_message_id,
                        "text": msg.text or "",
                        "message_id": message_id,
                        "status": receipt.status,
                        "conversation_id": str(conv_id),
                    },
                },
            )

            await session.commit()
    finally:
        if "engine" not in ctx:
            await engine.dispose()
        if redis_owned:
            await redis.aclose()

    return {"message_id": message_id, "status": receipt.status}


async def _persist_outbound(session, msg: OutboundMessage, message_id: str, receipt) -> None:
    cust_id = (await session.execute(
        text(
            "INSERT INTO customers (tenant_id, phone_e164) VALUES (:t, :p) "
            "ON CONFLICT (tenant_id, phone_e164) DO UPDATE SET phone_e164 = EXCLUDED.phone_e164 "
            "RETURNING id"
        ),
        {"t": msg.tenant_id, "p": msg.to_phone_e164},
    )).scalar()
    conv_id = (await session.execute(
        text(
            "SELECT id FROM conversations WHERE tenant_id = :t AND customer_id = :c "
            "ORDER BY last_activity_at DESC LIMIT 1"
        ),
        {"t": msg.tenant_id, "c": cust_id},
    )).scalar()
    if conv_id is None:
        conv_id = (await session.execute(
            text("INSERT INTO conversations (tenant_id, customer_id) VALUES (:t, :c) RETURNING id"),
            {"t": msg.tenant_id, "c": cust_id},
        )).scalar()
        await session.execute(
            text("INSERT INTO conversation_state (conversation_id) VALUES (:c)"),
            {"c": conv_id},
        )
    await session.execute(
        text(
            "INSERT INTO messages "
            "(id, conversation_id, tenant_id, direction, text, channel_message_id, "
            "delivery_status, sent_at) "
            "VALUES (:id, :c, :t, 'outbound', :txt, :cmid, :st, :ts)"
        ),
        {
            "id": message_id,
            "c": conv_id,
            "t": msg.tenant_id,
            "txt": msg.text or "",
            "cmid": receipt.channel_message_id,
            "st": receipt.status,
            "ts": datetime.now(UTC),
        },
    )


class WorkerSettings:
    """arq worker settings for the **default** queue (latency-critical work).

    Run: ``uv run arq atendia.queue.worker.WorkerSettings``.

    Workflow jobs live on a separate queue so a slow workflow can't starve
    ``send_outbound``. See :class:`WorkflowWorkerSettings` below.
    """
    from arq.cron import cron

    from atendia.queue.followup_worker import poll_followups

    functions: ClassVar = [send_outbound, index_document, force_summary]
    cron_jobs: ClassVar = [
        # Phase 3d — fires once a minute. unique=True prevents two ticks
        # from overlapping if a single poll takes >60s under load.
        cron(poll_followups, second={0}, unique=True, run_at_startup=False),
    ]
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    max_jobs = 10
    keep_result = 0


class WorkflowWorkerSettings:
    """arq worker settings for the **workflows** queue.

    Run alongside the default worker:
    ``uv run arq atendia.queue.worker.WorkflowWorkerSettings``.

    The engine enqueues both fresh executions and delay-resumes here with
    ``_queue_name=arq:queue:workflows``. Splitting queues keeps a noisy
    workflow tenant from blocking outbound message delivery.
    """
    from arq.cron import cron

    from atendia.workflows.engine import WORKFLOW_QUEUE_NAME

    queue_name: ClassVar = WORKFLOW_QUEUE_NAME
    functions: ClassVar = [execute_workflow_step]
    cron_jobs: ClassVar = [
        cron(poll_workflow_triggers, second={5, 15, 25, 35, 45, 55}, unique=True),
    ]
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    # Workflows are bursty and slow; cap concurrency lower than the default
    # worker so a flood doesn't blow Redis connection limits.
    max_jobs = 5
    keep_result = 0
