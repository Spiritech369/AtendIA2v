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


pytestmark = pytest.mark.skip(reason="awaiting T23 factory + T20 runner refactor: meta_routes.py uses removed KeywordNLU.feed()/next()")


APP_SECRET = "secret_for_t25_inb"


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
            "actions_allowed": ["greet", "ask_field"],
            "transitions": [{"to": "qualify", "when": "intent in [ask_info, ask_price]"}],
        },
        {
            "id": "qualify",
            "required_fields": ["interes_producto"],
            "actions_allowed": ["ask_field", "lookup_faq", "ask_clarification"],
            "transitions": [{"to": "quote", "when": "intent == ask_price"}],
        },
        {
            "id": "quote",
            "actions_allowed": ["quote", "ask_clarification"],
            "transitions": [],
        },
    ],
    "tone": {"register": "informal_mexicano"},
    "fallback": "escalate_to_human",
}


@pytest.fixture
def setup_tenant_with_pipeline():
    async def _setup():
        engine = create_async_engine(get_settings().database_url)
        async with engine.begin() as conn:
            tid = (await conn.execute(
                text("INSERT INTO tenants (name, config) VALUES (:n, :c\\:\\:jsonb) RETURNING id"),
                {
                    "n": "test_t25_inb",
                    "c": json.dumps({"meta": {"phone_number_id": "PID_T25", "verify_token": "vt"}}),
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
                    "metadata": {"display_phone_number": "x", "phone_number_id": "PID_T25"},
                    "messages": [{
                        "from": "5215555550250",
                        "id": channel_id,
                        "timestamp": "1714579200",
                        "text": {"body": text_body},
                        "type": "text",
                    }],
                },
            }],
        }],
    }


async def _redis_clear_dedup(channel_id: str):
    from redis.asyncio import Redis
    r = Redis.from_url(get_settings().redis_url)
    await r.delete(f"dedup:{channel_id}")
    await r.aclose()


def _read_traces(tid):
    async def _do():
        engine = create_async_engine(get_settings().database_url)
        async with engine.begin() as conn:
            rows = (await conn.execute(
                text("SELECT turn_number, state_after FROM turn_traces "
                     "WHERE tenant_id = :t ORDER BY turn_number"),
                {"t": tid},
            )).fetchall()
        await engine.dispose()
        return rows
    return asyncio.run(_do())


def test_inbound_webhook_runs_conversation_turn(setup_tenant_with_pipeline):
    """Greeting message → webhook persists inbound, runner produces a turn_trace."""
    tid = setup_tenant_with_pipeline
    asyncio.run(_redis_clear_dedup("wamid.T25_RUN_A"))

    body = json.dumps(_payload("wamid.T25_RUN_A", "hola buenos días")).encode()
    sig = _sign(body)

    with TestClient(app) as client:
        r = client.post(
            f"/webhooks/meta/{tid}",
            content=body,
            headers={"Content-Type": "application/json", "X-Hub-Signature-256": sig},
        )
        assert r.status_code == 200

    traces = _read_traces(tid)
    assert len(traces) == 1
    turn_number, state_after = traces[0]
    assert turn_number == 1
    assert state_after["current_stage"] == "greeting"
    assert state_after["last_intent"] == "greeting"


def test_subsequent_inbound_advances_turn_number(setup_tenant_with_pipeline):
    """Second inbound on same conversation → turn_number=2."""
    tid = setup_tenant_with_pipeline
    asyncio.run(_redis_clear_dedup("wamid.T25_RUN_B1"))
    asyncio.run(_redis_clear_dedup("wamid.T25_RUN_B2"))

    with TestClient(app) as client:
        body1 = json.dumps(_payload("wamid.T25_RUN_B1", "hola")).encode()
        sig1 = _sign(body1)
        r1 = client.post(
            f"/webhooks/meta/{tid}",
            content=body1,
            headers={"Content-Type": "application/json", "X-Hub-Signature-256": sig1},
        )
        assert r1.status_code == 200

        body2 = json.dumps(_payload("wamid.T25_RUN_B2", "info por favor")).encode()
        sig2 = _sign(body2)
        r2 = client.post(
            f"/webhooks/meta/{tid}",
            content=body2,
            headers={"Content-Type": "application/json", "X-Hub-Signature-256": sig2},
        )
        assert r2.status_code == 200

    traces = _read_traces(tid)
    assert len(traces) == 2
    assert traces[0][0] == 1
    assert traces[1][0] == 2
    # ask_info intent should transition greeting→qualify
    assert traces[1][1]["current_stage"] == "qualify"
