import pytest

from atendia.webhooks.deduplication import (
    DEDUP_TTL_SECONDS,
    is_duplicate,
)


@pytest.mark.asyncio
async def test_first_call_is_not_duplicate(redis_client):
    await redis_client.delete("dedup:test_t11_a")
    assert await is_duplicate(redis_client, "test_t11_a") is False


@pytest.mark.asyncio
async def test_second_call_is_duplicate(redis_client):
    await redis_client.delete("dedup:test_t11_b")
    assert await is_duplicate(redis_client, "test_t11_b") is False
    assert await is_duplicate(redis_client, "test_t11_b") is True


@pytest.mark.asyncio
async def test_ttl_is_set(redis_client):
    await redis_client.delete("dedup:test_t11_c")
    await is_duplicate(redis_client, "test_t11_c")
    ttl = await redis_client.ttl("dedup:test_t11_c")
    assert 0 < ttl <= DEDUP_TTL_SECONDS


@pytest.mark.asyncio
async def test_ttl_constant_is_24h():
    """Sanity: 24h matches Meta's recommendation."""
    assert DEDUP_TTL_SECONDS == 24 * 3600
