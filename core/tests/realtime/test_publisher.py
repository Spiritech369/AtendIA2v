import asyncio
import json

import pytest

from atendia.realtime.publisher import channel_for, publish_event


@pytest.mark.asyncio
async def test_publish_event_sends_json_on_correct_channel(redis_client):
    pubsub = redis_client.pubsub()
    channel = channel_for(tenant_id="t21", conversation_id="c1")
    assert channel == "tenant:t21:conversation:c1"

    await pubsub.subscribe(channel)
    # Drain the subscribe-ack message
    await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)

    # Publish from the same Redis client (separate publisher in production,
    # but for the test we just publish on the connection).
    await publish_event(
        redis_client,
        tenant_id="t21",
        conversation_id="c1",
        event={"type": "message_received", "data": {"text": "hola"}},
    )

    # Read the published message
    msg = None
    for _ in range(10):
        msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.5)
        if msg is not None:
            break
        await asyncio.sleep(0.05)

    assert msg is not None, "did not receive published event"
    payload = json.loads(msg["data"])
    assert payload == {"type": "message_received", "data": {"text": "hola"}}

    await pubsub.unsubscribe(channel)
    await pubsub.aclose()


def test_channel_for_format():
    assert channel_for(tenant_id="abc", conversation_id="xyz") == "tenant:abc:conversation:xyz"
    assert channel_for(tenant_id="dinamomotos", conversation_id="conv-uuid") == "tenant:dinamomotos:conversation:conv-uuid"
