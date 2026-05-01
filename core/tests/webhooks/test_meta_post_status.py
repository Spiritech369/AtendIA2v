import asyncio
import hashlib
import hmac
import json
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from atendia.config import get_settings
from atendia.main import app


APP_SECRET = "test_app_secret_for_t14"


@pytest.fixture(autouse=True)
def set_app_secret(monkeypatch):
    monkeypatch.setenv("ATENDIA_V2_META_APP_SECRET", APP_SECRET)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _sign(body: bytes) -> str:
    return "sha256=" + hmac.new(
        APP_SECRET.encode("utf-8"), body, hashlib.sha256
    ).hexdigest()


@pytest.fixture
def setup_tenant_with_outbound_message():
    """Seed: tenant with meta config, customer, conversation, and one
    outbound message with channel_message_id='wamid.test_t14_sent'.
    """
    async def _setup():
        engine = create_async_engine(get_settings().database_url)
        async with engine.begin() as conn:
            tid = (await conn.execute(
                text("INSERT INTO tenants (name, config) VALUES (:n, :c\\:\\:jsonb) RETURNING id"),
                {
                    "n": "test_t14_status",
                    "c": json.dumps({"meta": {"phone_number_id": "PID", "verify_token": "vt"}}),
                },
            )).scalar()
            cid = (await conn.execute(
                text("INSERT INTO customers (tenant_id, phone_e164) VALUES (:t, '+5215555550140') RETURNING id"),
                {"t": tid},
            )).scalar()
            conv_id = (await conn.execute(
                text("INSERT INTO conversations (tenant_id, customer_id) VALUES (:t, :c) RETURNING id"),
                {"t": tid, "c": cid},
            )).scalar()
            await conn.execute(
                text("INSERT INTO conversation_state (conversation_id) VALUES (:c)"),
                {"c": conv_id},
            )
            msg_id = uuid4()
            await conn.execute(
                text(
                    "INSERT INTO messages "
                    "(id, conversation_id, tenant_id, direction, text, channel_message_id, "
                    "delivery_status, sent_at) "
                    "VALUES (:id, :c, :t, 'outbound', 'hola desde el bot', "
                    "'wamid.test_t14_sent', 'sent', :ts)"
                ),
                {"id": msg_id, "c": conv_id, "t": tid, "ts": datetime.now(timezone.utc)},
            )
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


def _status_payload(channel_message_id: str, status_value: str) -> dict:
    return {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "WABA_ID",
            "changes": [{
                "field": "messages",
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {"display_phone_number": "5215555000000", "phone_number_id": "PID"},
                    "statuses": [{
                        "id": channel_message_id,
                        "status": status_value,
                        "timestamp": "1714579260",
                        "recipient_id": "5215555550140",
                    }],
                },
            }],
        }],
    }


def _read_delivery_status(channel_message_id):
    async def _do():
        engine = create_async_engine(get_settings().database_url)
        async with engine.begin() as conn:
            row = (await conn.execute(
                text("SELECT delivery_status FROM messages WHERE channel_message_id = :cm"),
                {"cm": channel_message_id},
            )).scalar()
        await engine.dispose()
        return row
    return asyncio.run(_do())


def test_status_payload_updates_delivery_status(setup_tenant_with_outbound_message):
    tid = setup_tenant_with_outbound_message
    body = json.dumps(_status_payload("wamid.test_t14_sent", "delivered")).encode("utf-8")
    sig = _sign(body)

    with TestClient(app) as client:
        r = client.post(
            f"/webhooks/meta/{tid}",
            content=body,
            headers={"Content-Type": "application/json", "X-Hub-Signature-256": sig},
        )
        assert r.status_code == 200
        body_resp = r.json()
        assert body_resp["statuses"] == 1

    assert _read_delivery_status("wamid.test_t14_sent") == "delivered"


def test_status_payload_for_unknown_channel_message_id_is_noop(setup_tenant_with_outbound_message):
    """Receiving a status for a message we don't have should not error or affect existing rows."""
    tid = setup_tenant_with_outbound_message
    body = json.dumps(_status_payload("wamid.never_seen_t14", "read")).encode("utf-8")
    sig = _sign(body)

    with TestClient(app) as client:
        r = client.post(
            f"/webhooks/meta/{tid}",
            content=body,
            headers={"Content-Type": "application/json", "X-Hub-Signature-256": sig},
        )
        assert r.status_code == 200

    # The seeded outbound message must remain at 'sent'
    assert _read_delivery_status("wamid.test_t14_sent") == "sent"
