import asyncio

import pytest

from atendia.queue.circuit_breaker import (
    OPEN_DURATION_SECONDS,
    THRESHOLD,
    WINDOW_SECONDS,
    is_open,
    record_failure,
    record_success,
)


@pytest.fixture(autouse=True)
async def clear_breaker_keys(redis_client):
    """Clear breaker keys for our test tenants before/after each test."""
    test_tenants = ["t19_a", "t19_b", "t19_c", "t19_d", "t19_e"]
    for tid in test_tenants:
        await redis_client.delete(f"breaker:fail:{tid}", f"breaker:open:{tid}")
    yield
    for tid in test_tenants:
        await redis_client.delete(f"breaker:fail:{tid}", f"breaker:open:{tid}")


def test_constants_match_design():
    assert THRESHOLD == 10
    assert WINDOW_SECONDS == 60
    assert OPEN_DURATION_SECONDS == 30


@pytest.mark.asyncio
async def test_initially_circuit_is_closed(redis_client):
    assert await is_open(redis_client, "t19_a") is False


@pytest.mark.asyncio
async def test_single_failure_does_not_open_circuit(redis_client):
    await record_failure(redis_client, "t19_a")
    assert await is_open(redis_client, "t19_a") is False


@pytest.mark.asyncio
async def test_threshold_failures_open_circuit(redis_client):
    for _ in range(THRESHOLD):
        await record_failure(redis_client, "t19_b")
    assert await is_open(redis_client, "t19_b") is True


@pytest.mark.asyncio
async def test_record_success_resets_counters(redis_client):
    for _ in range(THRESHOLD):
        await record_failure(redis_client, "t19_c")
    assert await is_open(redis_client, "t19_c") is True

    await record_success(redis_client, "t19_c")
    assert await is_open(redis_client, "t19_c") is False

    # And the failure counter is gone too
    assert await redis_client.get(f"breaker:fail:t19_c") is None


@pytest.mark.asyncio
async def test_failures_for_different_tenants_do_not_mix(redis_client):
    for _ in range(THRESHOLD):
        await record_failure(redis_client, "t19_d")
    assert await is_open(redis_client, "t19_d") is True
    assert await is_open(redis_client, "t19_e") is False  # different tenant


@pytest.mark.asyncio
async def test_open_circuit_has_ttl_close_to_open_duration(redis_client):
    for _ in range(THRESHOLD):
        await record_failure(redis_client, "t19_d")
    ttl = await redis_client.ttl(f"breaker:open:t19_d")
    assert 0 < ttl <= OPEN_DURATION_SECONDS


@pytest.mark.asyncio
async def test_failure_counter_has_window_ttl(redis_client):
    await record_failure(redis_client, "t19_d")
    ttl = await redis_client.ttl(f"breaker:fail:t19_d")
    assert 0 < ttl <= WINDOW_SECONDS
