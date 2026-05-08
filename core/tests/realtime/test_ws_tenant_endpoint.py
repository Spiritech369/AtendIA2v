"""Phase 4 T15 — /ws/tenants/:tid endpoint + tenant-channel fan-out."""
from __future__ import annotations

import asyncio
import json
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from atendia.api._auth_helpers import SESSION_COOKIE, issue_jwt
from atendia.config import get_settings
from atendia.main import app
from atendia.realtime.publisher import publish_event


@pytest.fixture(autouse=True)
def set_secret(monkeypatch):
    monkeypatch.setenv(
        "ATENDIA_V2_AUTH_SESSION_SECRET",
        "test-secret-for-t15-ws-tenant-32-bytes-min",
    )
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _operator_jwt(tenant_id: UUID) -> str:
    return issue_jwt(
        user_id=uuid4(),
        tenant_id=tenant_id,
        role="operator",
        email="op@dinamo.com",
    )


def _superadmin_jwt() -> str:
    return issue_jwt(
        user_id=uuid4(),
        tenant_id=None,
        role="superadmin",
        email="root@dinamo.com",
    )


def test_tenant_ws_rejects_without_cookie():
    client = TestClient(app)
    with pytest.raises(Exception):
        with client.websocket_connect("/ws/tenants/some-tenant"):
            pass


def test_tenant_ws_rejects_with_invalid_cookie():
    client = TestClient(app)
    client.cookies.set(SESSION_COOKIE, "not-a-real-jwt")
    with pytest.raises(Exception):
        with client.websocket_connect("/ws/tenants/some-tenant"):
            pass


def test_tenant_ws_rejects_operator_subscribing_to_other_tenant():
    my_tid = uuid4()
    their_tid = uuid4()
    client = TestClient(app)
    client.cookies.set(SESSION_COOKIE, _operator_jwt(my_tid))
    with pytest.raises(Exception):
        with client.websocket_connect(f"/ws/tenants/{their_tid}"):
            pass


@pytest.mark.asyncio
async def test_tenant_ws_receives_events_from_any_conversation(redis_client):
    """End-to-end: operator subscribes to /ws/tenants/T, publish a per-conv
    event to ANY conversation in T → the tenant channel publishes the
    enriched event (with conversation_id) → WS client sees it."""
    tenant_id = uuid4()
    conv_id = uuid4()

    received: list[str] = []

    def _connect_and_receive():
        client = TestClient(app)
        client.cookies.set(SESSION_COOKIE, _operator_jwt(tenant_id))
        with client.websocket_connect(f"/ws/tenants/{tenant_id}") as ws:
            received.append("ready")
            data = ws.receive_text()
            received.append(data)

    consumer_task = asyncio.create_task(asyncio.to_thread(_connect_and_receive))

    for _ in range(50):
        if "ready" in received:
            break
        await asyncio.sleep(0.05)
    await asyncio.sleep(0.2)  # let pubsub.subscribe settle

    await publish_event(
        redis_client,
        tenant_id=str(tenant_id),
        conversation_id=str(conv_id),
        event={"type": "message_received", "data": {"text": "hola tenant ws"}},
    )

    await asyncio.wait_for(consumer_task, timeout=5.0)

    assert len(received) == 2
    parsed = json.loads(received[1])
    assert parsed["type"] == "message_received"
    assert parsed["data"]["text"] == "hola tenant ws"
    # Tenant channel enriches with conversation_id so the dashboard can
    # demultiplex without an extra lookup.
    assert parsed["conversation_id"] == str(conv_id)


@pytest.mark.asyncio
async def test_tenant_ws_allows_superadmin_for_any_tenant(redis_client):
    tenant_id = uuid4()
    conv_id = uuid4()

    received: list[str] = []

    def _connect_and_receive():
        client = TestClient(app)
        client.cookies.set(SESSION_COOKIE, _superadmin_jwt())
        with client.websocket_connect(f"/ws/tenants/{tenant_id}") as ws:
            received.append("ready")
            data = ws.receive_text()
            received.append(data)

    consumer_task = asyncio.create_task(asyncio.to_thread(_connect_and_receive))

    for _ in range(50):
        if "ready" in received:
            break
        await asyncio.sleep(0.05)
    await asyncio.sleep(0.2)

    await publish_event(
        redis_client,
        tenant_id=str(tenant_id),
        conversation_id=str(conv_id),
        event={"type": "handoff_requested"},
    )

    await asyncio.wait_for(consumer_task, timeout=5.0)
    assert len(received) == 2
    parsed = json.loads(received[1])
    assert parsed["type"] == "handoff_requested"
