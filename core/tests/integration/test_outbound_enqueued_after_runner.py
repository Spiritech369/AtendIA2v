import asyncio
import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from atendia.config import get_settings
from atendia.main import app


APP_SECRET = "secret_for_t26_dispatch"


@pytest.fixture(autouse=True)
def set_creds(monkeypatch):
    monkeypatch.setenv("ATENDIA_V2_META_APP_SECRET", APP_SECRET)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _sign(body: bytes) -> str:
    return "sha256=" + hmac.new(APP_SECRET.encode("utf-8"), body, hashlib.sha256).hexdigest()


PIPELINE = {
    "version": 1,
    "stages": [
        {
            "id": "greeting",
            "actions_allowed": ["greet"],
            "transitions": [{"to": "qualify", "when": "intent in [ask_info, ask_price]"}],
        },
        {
            "id": "qualify",
            "actions_allowed": ["ask_field", "lookup_faq", "ask_clarification"],
            "transitions": [],
        },
    ],
    "tone": {"register": "informal_mexicano"},
    "fallback": "escalate_to_human",
}


@pytest.fixture
def setup_tenant():
    async def _setup():
        engine = create_async_engine(get_settings().database_url)
        async with engine.begin() as conn:
            tid = (await conn.execute(
                text("INSERT INTO tenants (name, config) VALUES (:n, :c\\:\\:jsonb) RETURNING id"),
                {
                    "n": "test_t26_disp",
                    "c": json.dumps({"meta": {"phone_number_id": "PID_T26", "verify_token": "vt"}}),
                },
            )).scalar()
            await conn.execute(
                text("INSERT INTO tenant_pipelines (tenant_id, version, definition, active) "
                     "VALUES (:t, 1, :d\\:\\:jsonb, true)"),
                {"t": tid, "d": json.dumps(PIPELINE)},
            )
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


def _payload(channel_id: str, text_body: str) -> dict:
    return {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "WABA",
            "changes": [{
                "field": "messages",
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {"display_phone_number": "x", "phone_number_id": "PID_T26"},
                    "messages": [{
                        "from": "5215555550260",
                        "id": channel_id,
                        "timestamp": "1714579200",
                        "text": {"body": text_body},
                        "type": "text",
                    }],
                },
            }],
        }],
    }


async def _redis_clear(channel_id: str):
    from redis.asyncio import Redis
    r = Redis.from_url(get_settings().redis_url)
    await r.delete(f"dedup:{channel_id}")
    # Clear arq queue keys that might be left over
    await r.aclose()


def _count_arq_jobs():
    """Count jobs currently queued in arq's default queue."""
    async def _do():
        from redis.asyncio import Redis
        r = Redis.from_url(get_settings().redis_url)
        # arq uses 'arq:queue' for the queue and 'arq:job:<id>' per job
        keys = await r.keys("arq:job:out:*")
        await r.aclose()
        return len(keys)
    return asyncio.run(_do())


def test_inbound_greeting_enqueues_outbound_greet_text(setup_tenant):
    tid = setup_tenant
    asyncio.run(_redis_clear("wamid.T26_GREET"))

    body = json.dumps(_payload("wamid.T26_GREET", "hola buenos días")).encode()
    sig = _sign(body)

    jobs_before = _count_arq_jobs()
    with TestClient(app) as client:
        r = client.post(
            f"/webhooks/meta/{tid}",
            content=body,
            headers={"Content-Type": "application/json", "X-Hub-Signature-256": sig},
        )
        assert r.status_code == 200

    jobs_after = _count_arq_jobs()
    assert jobs_after == jobs_before + 1, (
        f"expected exactly one new arq job after greeting; before={jobs_before}, after={jobs_after}"
    )
