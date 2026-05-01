import json

import httpx
import pytest
import respx
from arq.worker import Retry
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from atendia.config import get_settings
from atendia.queue.circuit_breaker import (
    OPEN_DURATION_SECONDS,
    THRESHOLD,
    is_open,
    record_failure,
)
from atendia.queue.worker import send_outbound


@pytest.fixture(autouse=True)
def set_meta_creds(monkeypatch):
    monkeypatch.setenv("ATENDIA_V2_META_APP_SECRET", "secret_t20")
    monkeypatch.setenv("ATENDIA_V2_META_ACCESS_TOKEN", "TOKEN_T20")
    monkeypatch.setenv("ATENDIA_V2_META_API_VERSION", "v21.0")
    monkeypatch.setenv("ATENDIA_V2_META_BASE_URL", "https://graph.facebook.com")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def setup_tenant():
    import asyncio

    async def _setup():
        engine = create_async_engine(get_settings().database_url)
        async with engine.begin() as conn:
            tid = (await conn.execute(
                text("INSERT INTO tenants (name, config) VALUES (:n, :c\\:\\:jsonb) RETURNING id"),
                {
                    "n": "test_t20_breaker",
                    "c": json.dumps({"meta": {"phone_number_id": "PID_T20", "verify_token": "vt_t20"}}),
                },
            )).scalar()
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


@pytest.fixture(autouse=True)
async def clear_breaker_state(redis_client, setup_tenant):
    """Reset breaker keys for the tenant before/after each test."""
    tid = str(setup_tenant)
    await redis_client.delete(f"breaker:fail:{tid}", f"breaker:open:{tid}")
    yield
    await redis_client.delete(f"breaker:fail:{tid}", f"breaker:open:{tid}")


def _msg_dict(tid: str, idem: str) -> dict:
    return {
        "tenant_id": tid,
        "to_phone_e164": "+5215555550200",
        "text": "circuit breaker test",
        "idempotency_key": idem,
        "metadata": {},
    }


@pytest.mark.asyncio
@respx.mock
async def test_open_circuit_raises_retry_without_calling_meta(setup_tenant, redis_client):
    """When the breaker is already open, the worker should defer immediately."""
    tid = str(setup_tenant)
    # Pre-open the breaker
    for _ in range(THRESHOLD):
        await record_failure(redis_client, tid)
    assert await is_open(redis_client, tid) is True

    # Set up a route — but expect it NOT to be called
    route = respx.post(
        "https://graph.facebook.com/v21.0/PID_T20/messages"
    ).mock(return_value=httpx.Response(200, json={"messaging_product": "whatsapp", "messages": [{"id": "wamid.x"}]}))

    with pytest.raises(Retry):
        await send_outbound(
            {"redis": redis_client, "job_try": 1},
            _msg_dict(tid, "test_t20_open_a"),
        )

    assert route.called is False


@pytest.mark.asyncio
@respx.mock
async def test_successful_send_records_success_clears_failures(setup_tenant, redis_client):
    """A successful send clears any prior failure counter."""
    tid = str(setup_tenant)
    # Build up a few (sub-threshold) failures
    await record_failure(redis_client, tid)
    await record_failure(redis_client, tid)
    assert await redis_client.get(f"breaker:fail:{tid}") == b"2"

    respx.post(
        "https://graph.facebook.com/v21.0/PID_T20/messages"
    ).mock(return_value=httpx.Response(
        200, json={"messaging_product": "whatsapp", "messages": [{"id": "wamid.OK"}]}
    ))

    result = await send_outbound(
        {"redis": redis_client, "job_try": 1},
        _msg_dict(tid, "test_t20_success_a"),
    )
    assert result["status"] == "sent"

    # record_success cleared the counter
    assert await redis_client.get(f"breaker:fail:{tid}") is None


@pytest.mark.asyncio
@respx.mock
async def test_permanent_failure_records_failure(setup_tenant, redis_client):
    """A permanent (4xx) failure increments the breaker counter."""
    tid = str(setup_tenant)
    respx.post(
        "https://graph.facebook.com/v21.0/PID_T20/messages"
    ).mock(return_value=httpx.Response(
        400, json={"error": {"code": 131000, "message": "Recipient not on WhatsApp"}}
    ))

    result = await send_outbound(
        {"redis": redis_client, "job_try": 1},
        _msg_dict(tid, "test_t20_fail_a"),
    )
    assert result["status"] == "failed"
    # Failure counter incremented
    assert await redis_client.get(f"breaker:fail:{tid}") == b"1"


@pytest.mark.asyncio
async def test_worker_uses_redis_from_settings_when_ctx_has_no_redis(setup_tenant, redis_client):
    """If ctx doesn't include 'redis' (e.g., direct call without arq context),
    the worker should fall back gracefully — it will create a Redis client itself."""
    # No respx mock — we don't expect to reach the HTTP call because the breaker is open.
    tid = str(setup_tenant)
    for _ in range(THRESHOLD):
        await record_failure(redis_client, tid)
    assert await is_open(redis_client, tid) is True

    with pytest.raises(Retry):
        await send_outbound(
            {"job_try": 1},  # no 'redis' key
            _msg_dict(tid, "test_t20_no_redis_ctx"),
        )
