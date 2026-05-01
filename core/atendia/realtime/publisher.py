import json

from redis.asyncio import Redis


def channel_for(*, tenant_id: str, conversation_id: str) -> str:
    """Canonical Pub/Sub channel name for a (tenant, conversation) pair."""
    return f"tenant:{tenant_id}:conversation:{conversation_id}"


async def publish_event(
    redis: Redis,
    *,
    tenant_id: str,
    conversation_id: str,
    event: dict,
) -> int:
    """Publish a JSON-encoded event to the per-conversation Redis Pub/Sub channel.

    Returns the number of subscribers who received the message
    (0 if no one is listening — that's OK, fire-and-forget).
    """
    channel = channel_for(tenant_id=tenant_id, conversation_id=conversation_id)
    return await redis.publish(channel, json.dumps(event))
