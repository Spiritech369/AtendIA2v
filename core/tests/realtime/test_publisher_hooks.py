import asyncio
import hashlib
import hmac
import json
from datetime import datetime, timezone
from uuid import uuid4

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from atendia.config import get_settings
from atendia.main import app
from atendia.queue.worker import send_outbound
from atendia.realtime.publisher import channel_for


APP_SECRET = "secret_t22"


@pytest.fixture(autouse=True)
def set_creds(monkeypatch):
    monkeypatch.setenv("ATENDIA_V2_META_APP_SECRET", APP_SECRET)
    monkeypatch.setenv("ATENDIA_V2_META_ACCESS_TOKEN", "TOKEN_T22")
    monkeypatch.setenv("ATENDIA_V2_META_API_VERSION", "v21.0")
    monkeypatch.setenv("ATENDIA_V2_META_BASE_URL", "https://graph.facebook.com")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _sign(body: bytes) -> str:
    return "sha256=" + hmac.new(APP_SECRET.encode("utf-8"), body, hashlib.sha256).hexdigest()


@pytest.fixture
def setup_tenant():
    async def _setup():
        engine = create_async_engine(get_settings().database_url)
        async with engine.begin() as conn:
            tid = (await conn.execute(
                text("INSERT INTO tenants (name, config) VALUES (:n, :c\\:\\:jsonb) RETURNING id"),
                {
                    "n": "test_t22_pub",
                    "c": json.dumps({"meta": {"phone_number_id": "PID_T22", "verify_token": "vt_t22"}}),
                },
            )).scalar()
        await engine.dispose()
        return tid

    async def _cleanup(tid):
        engine = create_async_engine(get_settings().database_url)
        async with engine.begin() as conn:
            await conn.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": tid})
        await engine.dispose()

    tid = asyncio.run(_setup())
    yield tid
    asyncio.run(_cleanup(tid))


async def _redis_clear_dedup(channel_message_id: str):
    from redis.asyncio import Redis
    r = Redis.from_url(get_settings().redis_url)
    await r.delete(f"dedup:{channel_message_id}")
    await r.aclose()


def _clear_dedup_sync(channel_message_id):
    asyncio.run(_redis_clear_dedup(channel_message_id))


async def _find_conversation(tid):
    engine = create_async_engine(get_settings().database_url)
    async with engine.begin() as conn:
        row = (await conn.execute(
            text("SELECT id FROM conversations WHERE tenant_id = :t ORDER BY created_at DESC LIMIT 1"),
            {"t": tid},
        )).scalar()
    await engine.dispose()
    return row


@pytest.mark.asyncio
async def test_inbound_webhook_publishes_message_received(setup_tenant, redis_client):
    tid = setup_tenant
    payload = {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "WABA",
            "changes": [{
                "field": "messages",
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {"display_phone_number": "x", "phone_number_id": "PID_T22"},
                    "messages": [{
                        "from": "5215555550220",
                        "id": "wamid.T22_INB_X",
                        "timestamp": "1714579200",
                        "text": {"body": "hola pub"},
                        "type": "text",
                    }],
                },
            }],
        }],
    }
    body = json.dumps(payload).encode()
    sig = _sign(body)
    await _redis_clear_dedup("wamid.T22_INB_X")

    # Subscribe BEFORE the POST so we don't miss the publish.
    pubsub = redis_client.pubsub()
    # We don't know the conversation_id yet — subscribe to a pattern that catches all this tenant's conversations.
    pattern = f"tenant:{tid}:conversation:*"
    await pubsub.psubscribe(pattern)
    # Drain the subscribe-ack
    await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.5)

    def _post():
        with TestClient(app) as client:
            return client.post(
                f"/webhooks/meta/{tid}",
                content=body,
                headers={"Content-Type": "application/json", "X-Hub-Signature-256": sig},
            )

    # Run the POST in a thread so the Redis pubsub.get_message can keep awaiting
    r = await asyncio.to_thread(_post)
    assert r.status_code == 200

    # Read the published event
    msg = None
    for _ in range(40):
        msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.1)
        if msg is not None and msg.get("type") == "pmessage":
            break
        await asyncio.sleep(0.05)

    assert msg is not None and msg.get("type") == "pmessage", "no pmessage received within timeout"
    parsed = json.loads(msg["data"])
    assert parsed["type"] == "message_received"
    assert parsed["data"]["channel_message_id"] == "wamid.T22_INB_X"
    assert parsed["data"]["text"] == "hola pub"

    await pubsub.punsubscribe(pattern)
    await pubsub.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_outbound_worker_publishes_message_sent(setup_tenant, redis_client):
    tid = setup_tenant
    respx.post(
        "https://graph.facebook.com/v21.0/PID_T22/messages"
    ).mock(return_value=httpx.Response(
        200, json={"messaging_product": "whatsapp", "messages": [{"id": "wamid.T22_OUT_Y"}]}
    ))

    pubsub = redis_client.pubsub()
    pattern = f"tenant:{tid}:conversation:*"
    await pubsub.psubscribe(pattern)
    await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.5)

    msg_dict = {
        "tenant_id": str(tid),
        "to_phone_e164": "+5215555550221",
        "text": "saliendo desde el worker",
        "idempotency_key": "test_t22_pub_out",
        "metadata": {},
    }
    result = await send_outbound({"redis": redis_client, "job_try": 1}, msg_dict)
    assert result["status"] == "sent"

    msg = None
    for _ in range(40):
        msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.1)
        if msg is not None and msg.get("type") == "pmessage":
            break
        await asyncio.sleep(0.05)

    assert msg is not None and msg.get("type") == "pmessage"
    parsed = json.loads(msg["data"])
    assert parsed["type"] == "message_sent"
    assert parsed["data"]["channel_message_id"] == "wamid.T22_OUT_Y"
    assert parsed["data"]["text"] == "saliendo desde el worker"
    assert parsed["data"]["status"] == "sent"

    await pubsub.punsubscribe(pattern)
    await pubsub.aclose()
