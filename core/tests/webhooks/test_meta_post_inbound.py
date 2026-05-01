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


APP_SECRET = "test_app_secret_for_t13"


@pytest.fixture(autouse=True)
def set_app_secret(monkeypatch):
    monkeypatch.setenv("ATENDIA_V2_META_APP_SECRET", APP_SECRET)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def setup_tenant():
    async def _setup():
        engine = create_async_engine(get_settings().database_url)
        async with engine.begin() as conn:
            tid = (await conn.execute(
                text("INSERT INTO tenants (name, config) VALUES (:n, :c\\:\\:jsonb) RETURNING id"),
                {
                    "n": "test_t13_post",
                    "c": json.dumps({
                        "meta": {
                            "phone_number_id": "PID",
                            "verify_token": "vt_xyz",
                        }
                    }),
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


def _sign(body: bytes) -> str:
    return "sha256=" + hmac.new(
        APP_SECRET.encode("utf-8"), body, hashlib.sha256
    ).hexdigest()


def _inbound_payload(channel_msg_id: str = "wamid.T13_A", text_body: str = "hola test") -> dict:
    return {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "WABA_ID",
            "changes": [{
                "field": "messages",
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {"display_phone_number": "5215555000000", "phone_number_id": "PID"},
                    "messages": [{
                        "from": "5215555550013",
                        "id": channel_msg_id,
                        "timestamp": "1714579200",
                        "text": {"body": text_body},
                        "type": "text",
                    }],
                },
            }],
        }],
    }


def _count_messages(tid, channel_message_id):
    async def _do():
        engine = create_async_engine(get_settings().database_url)
        async with engine.begin() as conn:
            n = (await conn.execute(
                text("SELECT COUNT(*) FROM messages WHERE tenant_id = :t AND channel_message_id = :c"),
                {"t": tid, "c": channel_message_id},
            )).scalar()
        await engine.dispose()
        return n
    return asyncio.run(_do())


async def _redis_clear_dedup(channel_message_id: str):
    from redis.asyncio import Redis
    r = Redis.from_url(get_settings().redis_url)
    await r.delete(f"dedup:{channel_message_id}")
    await r.aclose()


def _clear_dedup_sync(channel_message_id):
    asyncio.run(_redis_clear_dedup(channel_message_id))


def test_meta_webhook_post_persists_inbound_message(setup_tenant):
    tid = setup_tenant
    payload = _inbound_payload(channel_msg_id="wamid.T13_FIRST")
    body = json.dumps(payload).encode("utf-8")
    sig = _sign(body)

    _clear_dedup_sync("wamid.T13_FIRST")

    with TestClient(app) as client:
        r = client.post(
            f"/webhooks/meta/{tid}",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": sig,
            },
        )
        assert r.status_code == 200, r.text
        body_resp = r.json()
        assert body_resp["status"] == "ok"
        assert body_resp["received"] == 1

    assert _count_messages(tid, "wamid.T13_FIRST") == 1


def test_meta_webhook_post_dedupes_duplicate_payload(setup_tenant):
    tid = setup_tenant
    payload = _inbound_payload(channel_msg_id="wamid.T13_DUP")
    body = json.dumps(payload).encode("utf-8")
    sig = _sign(body)

    _clear_dedup_sync("wamid.T13_DUP")

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

    # Only one row in messages despite two POSTs
    assert _count_messages(tid, "wamid.T13_DUP") == 1


def test_meta_webhook_post_403_when_signature_invalid(setup_tenant):
    tid = setup_tenant
    payload = _inbound_payload()
    body = json.dumps(payload).encode("utf-8")

    with TestClient(app) as client:
        r = client.post(
            f"/webhooks/meta/{tid}",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": "sha256=deadbeef",
            },
        )
        assert r.status_code == 403


def test_meta_webhook_post_400_when_body_not_json(setup_tenant):
    tid = setup_tenant
    body = b"not json"
    sig = _sign(body)

    with TestClient(app) as client:
        r = client.post(
            f"/webhooks/meta/{tid}",
            content=body,
            headers={"Content-Type": "application/json", "X-Hub-Signature-256": sig},
        )
        assert r.status_code == 400
