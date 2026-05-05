import asyncio
import hashlib
import hmac
import json
from decimal import Decimal

import pytest
import respx
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from atendia.config import get_settings
from atendia.main import app


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


def _ok_openai_response(intent="ask_info", entities=None, confidence=0.9,
                        sentiment="neutral", ambiguities=None,
                        model="gpt-4o-mini", tokens_in=480, tokens_out=80):
    """Helper: build a canonical OpenAI chat completion response."""
    payload = {
        "intent": intent,
        "entities": entities or {},
        "confidence": confidence,
        "sentiment": sentiment,
        "ambiguities": ambiguities or [],
    }
    return Response(
        200,
        json={
            "id": "chatcmpl-int",
            "object": "chat.completion",
            "created": 0,
            "model": model,
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": json.dumps(payload)},
                "finish_reason": "stop",
            }],
            "usage": {
                "prompt_tokens": tokens_in,
                "completion_tokens": tokens_out,
                "total_tokens": tokens_in + tokens_out,
            },
        },
    )


def _read_latest_trace(tid):
    async def _do():
        engine = create_async_engine(get_settings().database_url)
        async with engine.begin() as conn:
            row = (await conn.execute(
                text("""SELECT nlu_model, nlu_cost_usd, nlu_tokens_in, nlu_tokens_out, nlu_output
                        FROM turn_traces WHERE tenant_id = :t
                        ORDER BY created_at DESC LIMIT 1"""),
                {"t": tid},
            )).fetchone()
        await engine.dispose()
        return row
    return asyncio.run(_do())


def _read_latest_error_event(tid):
    async def _do():
        engine = create_async_engine(get_settings().database_url)
        async with engine.begin() as conn:
            row = (await conn.execute(
                text("""SELECT payload FROM events
                        WHERE tenant_id = :t AND type = 'error_occurred'
                        ORDER BY created_at DESC LIMIT 1"""),
                {"t": tid},
            )).fetchone()
        await engine.dispose()
        return row
    return asyncio.run(_do())


@respx.mock
def test_inbound_with_openai_nlu_mocked(monkeypatch, setup_tenant_with_pipeline):
    """T22: full inbound flow with OpenAI mocked.

    Asserts the resulting turn_trace has populated nlu_model + nlu_cost_usd."""
    monkeypatch.setenv("ATENDIA_V2_NLU_PROVIDER", "openai")
    monkeypatch.setenv("ATENDIA_V2_OPENAI_API_KEY", "sk-test")
    get_settings.cache_clear()

    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=_ok_openai_response(intent="ask_price")
    )

    tid = setup_tenant_with_pipeline
    asyncio.run(_redis_clear_dedup("wamid.T22_OPENAI_OK"))

    body = json.dumps(_payload("wamid.T22_OPENAI_OK", "cuánto cuesta la 150Z?")).encode()
    sig = _sign(body)

    with TestClient(app) as client:
        resp = client.post(
            f"/webhooks/meta/{tid}",
            content=body,
            headers={"Content-Type": "application/json", "X-Hub-Signature-256": sig},
        )
    assert resp.status_code == 200

    row = _read_latest_trace(tid)
    assert row is not None
    nlu_model, cost, tin, tout, nlu_output = row
    assert nlu_model == "gpt-4o-mini"
    assert cost is not None and cost > 0
    assert tin == 480
    assert tout == 80
    assert nlu_output["intent"] == "ask_price"


@respx.mock
def test_inbound_when_openai_fails_emits_error_event_and_clarification(
    monkeypatch, setup_tenant_with_pipeline
):
    """T24: when OpenAI returns 503 on all retries, the runner falls back to
    intent=unclear. The webhook should:
      - Not crash (HTTP 200).
      - Emit an ERROR_OCCURRED event with payload.where == 'nlu'.
      - Persist a turn_trace row with cost = 0 and intent = unclear.
    """
    monkeypatch.setenv("ATENDIA_V2_NLU_PROVIDER", "openai")
    monkeypatch.setenv("ATENDIA_V2_OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("ATENDIA_V2_NLU_RETRY_DELAYS_MS", "[10,20]")
    get_settings.cache_clear()

    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=Response(503, json={"error": {"message": "down"}})
    )

    tid = setup_tenant_with_pipeline
    asyncio.run(_redis_clear_dedup("wamid.T24_OPENAI_FAIL"))

    body = json.dumps(_payload("wamid.T24_OPENAI_FAIL", "hola")).encode()
    sig = _sign(body)

    with TestClient(app) as client:
        resp = client.post(
            f"/webhooks/meta/{tid}",
            content=body,
            headers={"Content-Type": "application/json", "X-Hub-Signature-256": sig},
        )
    assert resp.status_code == 200

    trace_row = _read_latest_trace(tid)
    assert trace_row is not None
    _model, cost, _tin, _tout, nlu_output = trace_row
    assert cost == 0 or cost is None or cost == Decimal("0")
    assert nlu_output["intent"] == "unclear"
    assert any(a.startswith("nlu_error:") for a in nlu_output["ambiguities"])

    event_row = _read_latest_error_event(tid)
    assert event_row is not None
    assert event_row[0]["where"] == "nlu"
