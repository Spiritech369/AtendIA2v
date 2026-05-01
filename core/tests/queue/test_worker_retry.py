import json

import httpx
import pytest
import respx
from arq.worker import Retry
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from atendia.config import get_settings
from atendia.queue.worker import _is_transient, send_outbound


@pytest.fixture(autouse=True)
def set_meta_creds(monkeypatch):
    monkeypatch.setenv("ATENDIA_V2_META_APP_SECRET", "secret_t18")
    monkeypatch.setenv("ATENDIA_V2_META_ACCESS_TOKEN", "TOKEN_T18")
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
                    "n": "test_t18_retry",
                    "c": json.dumps({"meta": {"phone_number_id": "PID_T18", "verify_token": "vt_t18"}}),
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


async def _count_messages(tid):
    engine = create_async_engine(get_settings().database_url)
    async with engine.begin() as conn:
        n = (await conn.execute(
            text("SELECT COUNT(*) FROM messages WHERE tenant_id = :t"),
            {"t": tid},
        )).scalar()
    await engine.dispose()
    return n


def test_is_transient_recognizes_transport_error():
    assert _is_transient("transport_error: ConnectError: connection refused") is True


def test_is_transient_recognizes_5xx():
    assert _is_transient("meta_error_500: Internal Server Error") is True
    assert _is_transient("meta_error_503: Service Unavailable") is True


def test_is_transient_rejects_permanent_4xx():
    assert _is_transient("meta_error_131000: Recipient not on WhatsApp") is False


def test_is_transient_rejects_none():
    assert _is_transient(None) is False


@pytest.mark.asyncio
@respx.mock
async def test_transient_failure_raises_retry_first_time(setup_tenant):
    """First attempt: transient 503 → Retry raised, no row persisted."""
    tid = setup_tenant
    respx.post(
        "https://graph.facebook.com/v21.0/PID_T18/messages"
    ).mock(
        return_value=httpx.Response(
            503,
            json={"error": {"code": 503, "message": "service unavailable"}},
        )
    )

    msg_dict = {
        "tenant_id": str(tid),
        "to_phone_e164": "+5215555550180",
        "text": "transient try 1",
        "idempotency_key": "test_t18_retry_a",
        "metadata": {},
    }

    with pytest.raises(Retry) as exc_info:
        await send_outbound({"job_try": 1}, msg_dict)

    # arq.Retry stores defer in `defer_score` (ms) in this version
    assert exc_info.value.defer_score is not None

    # No row persisted — retry path bypasses _persist_outbound
    assert await _count_messages(tid) == 0


@pytest.mark.asyncio
@respx.mock
async def test_transient_failure_persists_after_max_retries(setup_tenant):
    """At job_try >= 4, give up and persist the failed row."""
    tid = setup_tenant
    respx.post(
        "https://graph.facebook.com/v21.0/PID_T18/messages"
    ).mock(
        return_value=httpx.Response(
            503,
            json={"error": {"code": 503, "message": "service unavailable"}},
        )
    )

    msg_dict = {
        "tenant_id": str(tid),
        "to_phone_e164": "+5215555550181",
        "text": "transient try 4",
        "idempotency_key": "test_t18_retry_b",
        "metadata": {},
    }

    result = await send_outbound({"job_try": 4}, msg_dict)
    assert result["status"] == "failed"
    assert await _count_messages(tid) == 1


@pytest.mark.asyncio
@respx.mock
async def test_permanent_failure_persists_immediately_no_retry(setup_tenant):
    """4xx with permanent error → persist immediately, no Retry."""
    tid = setup_tenant
    respx.post(
        "https://graph.facebook.com/v21.0/PID_T18/messages"
    ).mock(
        return_value=httpx.Response(
            400,
            json={"error": {"code": 131000, "message": "Recipient not on WhatsApp"}},
        )
    )

    msg_dict = {
        "tenant_id": str(tid),
        "to_phone_e164": "+5215555550999",
        "text": "permanent fail",
        "idempotency_key": "test_t18_retry_c",
        "metadata": {},
    }

    result = await send_outbound({"job_try": 1}, msg_dict)
    assert result["status"] == "failed"
    assert await _count_messages(tid) == 1
