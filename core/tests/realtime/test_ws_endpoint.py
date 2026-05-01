import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from atendia.config import get_settings
from atendia.main import app
from atendia.realtime.auth import issue_token
from atendia.realtime.publisher import publish_event


@pytest.fixture(autouse=True)
def set_secret(monkeypatch):
    monkeypatch.setenv("ATENDIA_V2_META_APP_SECRET", "secret_for_t24_ws")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_ws_rejects_connection_without_token():
    client = TestClient(app)
    with pytest.raises(Exception):
        with client.websocket_connect("/ws/conversations/conv-x"):
            pass


def test_ws_rejects_connection_with_invalid_token():
    client = TestClient(app)
    with pytest.raises(Exception):
        with client.websocket_connect("/ws/conversations/conv-x?token=NOT_A_REAL_JWT"):
            pass


@pytest.mark.asyncio
async def test_ws_receives_published_event(redis_client):
    """End-to-end: connect WS as tenant T, publish to T's channel, receive event."""
    tenant_id = "t24_ws_tenant"
    conv_id = "conv-t24-a"
    token = issue_token(tenant_id=tenant_id, ttl_seconds=600)

    # Use a thread to drive the synchronous TestClient WS, since asyncio.run
    # nesting is not allowed and TestClient.websocket_connect is sync.
    received: list[str] = []

    def _connect_and_receive():
        client = TestClient(app)
        with client.websocket_connect(
            f"/ws/conversations/{conv_id}?token={token}"
        ) as ws:
            # Wait briefly for the handler to subscribe to Redis
            received.append("ready")
            # Receive one message (will block up to default timeout)
            data = ws.receive_text()
            received.append(data)

    consumer_task = asyncio.create_task(asyncio.to_thread(_connect_and_receive))

    # Wait for the WS handler to subscribe to Redis before publishing.
    # Subscription happens during accept; we poll until "ready" appears,
    # then add a small grace for the pubsub.subscribe to land.
    for _ in range(50):
        if "ready" in received:
            break
        await asyncio.sleep(0.05)
    await asyncio.sleep(0.2)  # let pubsub.subscribe settle

    await publish_event(
        redis_client,
        tenant_id=tenant_id,
        conversation_id=conv_id,
        event={"type": "message_received", "data": {"text": "hola ws"}},
    )

    await asyncio.wait_for(consumer_task, timeout=5.0)

    # received[0] is "ready", received[1] is the JSON message
    assert len(received) == 2
    parsed = json.loads(received[1])
    assert parsed["type"] == "message_received"
    assert parsed["data"]["text"] == "hola ws"
