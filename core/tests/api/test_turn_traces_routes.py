"""Phase 4 T34-T35 — turn-trace list + detail."""
from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from atendia.api._auth_helpers import hash_password
from atendia.config import get_settings
from atendia.main import app


def _seed_with_traces() -> tuple[str, str, str, str, list[str]]:
    """Returns (tid, conv_id, email, password, [trace_ids])."""
    email = f"phase4_t34_{uuid4().hex[:8]}@dinamo.com"
    plain = "test-password-123"
    hashed = hash_password(plain)

    async def _do():
        engine = create_async_engine(get_settings().database_url)
        async with engine.begin() as conn:
            tid = (
                await conn.execute(
                    text("INSERT INTO tenants (name) VALUES (:n) RETURNING id"),
                    {"n": f"phase4_t34_{uuid4().hex[:8]}"},
                )
            ).scalar()
            await conn.execute(
                text(
                    "INSERT INTO tenant_users (tenant_id, email, role, password_hash) "
                    "VALUES (:t, :e, 'operator', :h)"
                ),
                {"t": tid, "e": email, "h": hashed},
            )
            cust = (
                await conn.execute(
                    text(
                        "INSERT INTO customers (tenant_id, phone_e164) "
                        "VALUES (:t, :p) RETURNING id"
                    ),
                    {"t": tid, "p": f"+5215555{uuid4().hex[:8]}"[:24]},
                )
            ).scalar()
            conv = (
                await conn.execute(
                    text(
                        "INSERT INTO conversations (tenant_id, customer_id) "
                        "VALUES (:t, :c) RETURNING id"
                    ),
                    {"t": tid, "c": cust},
                )
            ).scalar()
            await conn.execute(
                text("INSERT INTO conversation_state (conversation_id) VALUES (:c)"),
                {"c": conv},
            )
            tids: list[str] = []
            for i in range(3):
                trace_id = (
                    await conn.execute(
                        text(
                            "INSERT INTO turn_traces "
                            "(tenant_id, conversation_id, turn_number, "
                            " flow_mode, nlu_model, composer_model, "
                            " inbound_text, nlu_output, total_cost_usd, "
                            " total_latency_ms, bot_paused) "
                            "VALUES (:t, :c, :n, 'PLAN', 'gpt-4o-mini', 'gpt-4o', "
                            "        :it, :no\\:\\:jsonb, 0.0123, 250, false) "
                            "RETURNING id"
                        ),
                        {
                            "t": tid,
                            "c": conv,
                            "n": i + 1,
                            "it": f"hola turn {i}",
                            "no": json.dumps({"intent": f"intent_{i}"}),
                        },
                    )
                ).scalar()
                tids.append(str(trace_id))
        await engine.dispose()
        return str(tid), str(conv), tids

    tid, conv, tids = asyncio.run(_do())
    return tid, conv, email, plain, tids


@pytest.fixture
def operator_with_traces() -> Iterator[tuple[str, str, str, str, list[str]]]:
    seed = _seed_with_traces()
    yield seed
    async def _do():
        engine = create_async_engine(get_settings().database_url)
        async with engine.begin() as conn:
            await conn.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": seed[0]})
        await engine.dispose()
    asyncio.run(_do())


def _login(client: TestClient, email: str, plain: str) -> None:
    resp = client.post("/api/v1/auth/login", json={"email": email, "password": plain})
    assert resp.status_code == 200


def test_list_turn_traces(operator_with_traces):
    _, conv, email, plain, tids = operator_with_traces
    client = TestClient(app)
    _login(client, email, plain)

    resp = client.get(f"/api/v1/turn-traces?conversation_id={conv}")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["items"]) == 3
    # Ordered by turn_number ASC
    assert [it["turn_number"] for it in body["items"]] == [1, 2, 3]
    # Metadata only — payloads not in list response
    assert "nlu_output" not in body["items"][0]
    # Inbound preview is included so operators can scan without opening rows
    assert body["items"][0]["inbound_preview"] == "hola turn 0"


def test_list_turn_traces_404_other_tenant(operator_with_traces):
    other = _seed_with_traces()
    try:
        _, _, email, plain, _ = operator_with_traces
        client = TestClient(app)
        _login(client, email, plain)
        resp = client.get(f"/api/v1/turn-traces?conversation_id={other[1]}")
        assert resp.status_code == 404
    finally:
        async def _do():
            engine = create_async_engine(get_settings().database_url)
            async with engine.begin() as conn:
                await conn.execute(
                    text("DELETE FROM tenants WHERE id = :t"), {"t": other[0]}
                )
            await engine.dispose()
        asyncio.run(_do())


def test_get_turn_trace_returns_full_payload(operator_with_traces):
    _, _, email, plain, tids = operator_with_traces
    client = TestClient(app)
    _login(client, email, plain)

    resp = client.get(f"/api/v1/turn-traces/{tids[0]}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["nlu_output"] == {"intent": "intent_0"}
    assert body["inbound_text"] == "hola turn 0"
    assert body["composer_model"] == "gpt-4o"
    assert body["bot_paused"] is False


def test_get_turn_trace_404_other_tenant(operator_with_traces):
    other = _seed_with_traces()
    try:
        _, _, email, plain, _ = operator_with_traces
        client = TestClient(app)
        _login(client, email, plain)
        resp = client.get(f"/api/v1/turn-traces/{other[4][0]}")
        assert resp.status_code == 404
    finally:
        async def _do():
            engine = create_async_engine(get_settings().database_url)
            async with engine.begin() as conn:
                await conn.execute(
                    text("DELETE FROM tenants WHERE id = :t"), {"t": other[0]}
                )
            await engine.dispose()
        asyncio.run(_do())
