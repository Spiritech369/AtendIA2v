import json

from redis.asyncio import Redis


def channel_for(*, tenant_id: str, conversation_id: str) -> str:
    """Canonical Pub/Sub channel name for a (tenant, conversation) pair."""
    return f"tenant:{tenant_id}:conversation:{conversation_id}"


def tenant_channel_for(*, tenant_id: str) -> str:
    """Tenant-wide fan-out channel — every event for ANY conversation in
    the tenant lands here. Used by the operator dashboard's
    /ws/tenants/:tid endpoint (Phase 4 T15)."""
    return f"tenant:{tenant_id}"


async def publish_tenant_event(
    redis: Redis,
    *,
    tenant_id: str,
    event: dict,
) -> int:
    """Publish a tenant-scoped event with no conversation context — for
    config-shaped changes like pipeline edits, branding updates, or
    integration status flips that every open dashboard tab should react
    to. Fire-and-forget; returns the subscriber count for tests."""
    return await redis.publish(
        tenant_channel_for(tenant_id=tenant_id), json.dumps(event)
    )


async def publish_event(
    redis: Redis,
    *,
    tenant_id: str,
    conversation_id: str,
    event: dict,
) -> int:
    """Publish a JSON-encoded event to BOTH the per-conversation channel
    (Phase 2 — `/ws/conversations/:cid` clients) and the tenant-wide
    channel (Phase 4 — `/ws/tenants/:tid` operator dashboards).

    The tenant-channel payload is enriched with `conversation_id` so a
    dashboard subscribing to a tenant can demultiplex events back to
    individual conversations without an extra lookup.

    Returns the SUM of subscriber counts across both channels — useful
    for tests but not relied on in production (fire-and-forget).
    """
    per_conv_channel = channel_for(tenant_id=tenant_id, conversation_id=conversation_id)
    n_conv = await redis.publish(per_conv_channel, json.dumps(event))

    enriched = {**event, "conversation_id": str(conversation_id)}
    tenant_channel = tenant_channel_for(tenant_id=tenant_id)
    n_tenant = await redis.publish(tenant_channel, json.dumps(enriched))

    return n_conv + n_tenant
