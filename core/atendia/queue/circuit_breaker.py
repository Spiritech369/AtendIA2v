from redis.asyncio import Redis

THRESHOLD = 10
WINDOW_SECONDS = 60
OPEN_DURATION_SECONDS = 30


async def record_failure(redis: Redis, tenant_id: str) -> None:
    """Increment failure counter for tenant. Opens circuit if THRESHOLD reached."""
    fail_key = f"breaker:fail:{tenant_id}"
    n = await redis.incr(fail_key)
    if n == 1:
        await redis.expire(fail_key, WINDOW_SECONDS)
    if n >= THRESHOLD:
        await redis.set(f"breaker:open:{tenant_id}", "1", ex=OPEN_DURATION_SECONDS)


async def record_success(redis: Redis, tenant_id: str) -> None:
    """Reset failure counter and close circuit on a successful call."""
    await redis.delete(f"breaker:fail:{tenant_id}", f"breaker:open:{tenant_id}")


async def is_open(redis: Redis, tenant_id: str) -> bool:
    """Returns True if the circuit is currently open for this tenant."""
    return bool(await redis.exists(f"breaker:open:{tenant_id}"))
