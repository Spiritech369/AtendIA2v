from redis.asyncio import Redis

DEDUP_TTL_SECONDS = 24 * 3600  # 24h matches Meta's deduplication recommendation


async def is_duplicate(redis_client: Redis, message_id: str) -> bool:
    """Returns True if `message_id` was seen before (in the last 24h).

    Uses Redis SET NX with TTL: the first call inserts and returns False; subsequent
    calls within TTL find the key and return True.
    """
    key = f"dedup:{message_id}"
    inserted = await redis_client.set(key, "1", ex=DEDUP_TTL_SECONDS, nx=True)
    return not inserted
