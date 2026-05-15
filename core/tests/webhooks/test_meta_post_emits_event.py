import asyncio
import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from atendia.config import get_settings
from atendia.main import app

APP_SECRET = "test_app_secret_for_t15"


@pytest.fixture(autouse=True)
def set_app_secret(monkeypatch):
    monkeypatch.setenv("ATENDIA_V2_META_APP_SECRET", APP_SECRET)
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
            tid = (
                await conn.execute(
                    text(
                        "INSERT INTO tenants (name, config) VALUES (:n, :c\\:\\:jsonb) RETURNING id"
                    ),
                    {
                        "n": "test_t15_event",
                        "c": json.dumps({"meta": {"phone_number_id": "PID", "verify_token": "vt"}}),
                    },
                )
            ).scalar()
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


def _inbound_payload(channel_msg_id: str, text_body: str = "hola test") -> dict:
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "WABA_ID",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": "5215555000000",
                                "phone_number_id": "PID",
                            },
                            "messages": [
                                {
                                    "from": "5215555550150",
                                    "id": channel_msg_id,
                                    "timestamp": "1714579200",
                                    "text": {"body": text_body},
                                    "type": "text",
                                }
                            ],
                        },
                    }
                ],
            }
        ],
    }


def _read_events(tid):
    async def _do():
        engine = create_async_engine(get_settings().database_url)
        async with engine.begin() as conn:
            rows = (
                await conn.execute(
                    text(
                        "SELECT type, payload FROM events WHERE tenant_id = :t ORDER BY occurred_at"
                    ),
                    {"t": tid},
                )
            ).fetchall()
        await engine.dispose()
        return [(r[0], r[1]) for r in rows]

    return asyncio.run(_do())


async def _redis_clear_dedup(channel_message_id: str):
    from redis.asyncio import Redis

    r = Redis.from_url(get_settings().redis_url)
    await r.delete(f"dedup:{channel_message_id}")
    await r.aclose()


def _clear_dedup_sync(channel_message_id):
    asyncio.run(_redis_clear_dedup(channel_message_id))


def test_inbound_persistence_emits_message_received_event(setup_tenant):
    tid = setup_tenant
    _clear_dedup_sync("wamid.T15_E1")
    body = json.dumps(_inbound_payload("wamid.T15_E1", "hello t15")).encode("utf-8")
    sig = _sign(body)

    with TestClient(app) as client:
        r = client.post(
            f"/webhooks/meta/{tid}",
            content=body,
            headers={"Content-Type": "application/json", "X-Hub-Signature-256": sig},
        )
        assert r.status_code == 200

    events = _read_events(tid)
    types = [t for t, _ in events]
    assert "message_received" in types
    payload = next(p for t, p in events if t == "message_received")
    assert payload["channel_message_id"] == "wamid.T15_E1"
    assert payload["text"] == "hello t15"


def test_dedupe_does_not_double_emit_event(setup_tenant):
    """Same payload twice → only one event."""
    tid = setup_tenant
    _clear_dedup_sync("wamid.T15_DUP")
    body = json.dumps(_inbound_payload("wamid.T15_DUP", "dup test")).encode("utf-8")
    sig = _sign(body)

    with TestClient(app) as client:
        r1 = client.post(
            f"/webhooks/meta/{tid}",
            content=body,
            headers={"Content-Type": "application/json", "X-Hub-Signature-256": sig},
        )
        assert r1.status_code == 200
        r2 = client.post(
            f"/webhooks/meta/{tid}",
            content=body,
            headers={"Content-Type": "application/json", "X-Hub-Signature-256": sig},
        )
        assert r2.status_code == 200

    events = _read_events(tid)
    received_events = [e for e in events if e[0] == "message_received"]
    assert len(received_events) == 1
