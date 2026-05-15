"""Phase 4 T20-T23 — handoffs queue + assign/resolve + intervene/resume."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from atendia.api._auth_helpers import hash_password
from atendia.config import get_settings
from atendia.main import app


def _seed_with_handoffs(
    role: str = "operator", num_handoffs: int = 3
) -> tuple[str, str, str, str, str, list[str]]:
    """Returns (tid, uid, email, password, conv_id, [handoff_ids])."""
    email = f"phase4_t20_{role}_{uuid4().hex[:8]}@dinamo.com"
    plain = "test-password-123"
    hashed = hash_password(plain)

    async def _do():
        engine = create_async_engine(get_settings().database_url)
        async with engine.begin() as conn:
            tid = (
                await conn.execute(
                    text("INSERT INTO tenants (name) VALUES (:n) RETURNING id"),
                    {"n": f"phase4_t20_{uuid4().hex[:8]}"},
                )
            ).scalar()
            uid = (
                await conn.execute(
                    text(
                        "INSERT INTO tenant_users (tenant_id, email, role, password_hash) "
                        "VALUES (:t, :e, :r, :h) RETURNING id"
                    ),
                    {"t": tid, "e": email, "r": role, "h": hashed},
                )
            ).scalar()
            cust = (
                await conn.execute(
                    text(
                        "INSERT INTO customers (tenant_id, phone_e164, name) "
                        "VALUES (:t, :p, 'Cliente') RETURNING id"
                    ),
                    {"t": tid, "p": f"+5215555{uuid4().hex[:8]}"[:24]},
                )
            ).scalar()
            conv = (
                await conn.execute(
                    text(
                        "INSERT INTO conversations "
                        "(tenant_id, customer_id, current_stage) "
                        "VALUES (:t, :c, 'qualify') RETURNING id"
                    ),
                    {"t": tid, "c": cust},
                )
            ).scalar()
            await conn.execute(
                text("INSERT INTO conversation_state (conversation_id) VALUES (:c)"),
                {"c": conv},
            )
            base = datetime(2026, 5, 1, 12, 0, 0, tzinfo=timezone.utc)
            hids: list[str] = []
            for i in range(num_handoffs):
                hid = (
                    await conn.execute(
                        text(
                            "INSERT INTO human_handoffs "
                            "(conversation_id, tenant_id, reason, status, requested_at, payload) "
                            "VALUES (:c, :t, :r, :s, :ts, :p\\:\\:jsonb) RETURNING id"
                        ),
                        {
                            "c": conv,
                            "t": tid,
                            "r": f"reason {i}",
                            "s": "open",
                            "ts": base + timedelta(minutes=i),
                            "p": '{"customer":"Juan","reason_code":"NO_DATA"}',
                        },
                    )
                ).scalar()
                hids.append(str(hid))
        await engine.dispose()
        return str(tid), str(uid), str(conv), hids

    tid, uid, conv, hids = asyncio.run(_do())
    return tid, uid, email, plain, conv, hids


def _cleanup(tid: str) -> None:
    async def _do():
        engine = create_async_engine(get_settings().database_url)
        async with engine.begin() as conn:
            await conn.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": tid})
        await engine.dispose()

    asyncio.run(_do())


@pytest.fixture
def operator_with_handoffs() -> Iterator[tuple[str, str, str, str, str, list[str]]]:
    seed = _seed_with_handoffs()
    yield seed
    _cleanup(seed[0])


def _login(client: TestClient, email: str, password: str) -> str:
    resp = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["csrf_token"]


def test_list_handoffs_returns_tenant_scoped(operator_with_handoffs):
    tid, _, email, plain, _, hids = operator_with_handoffs
    client = TestClient(app)
    _login(client, email, plain)

    resp = client.get("/api/v1/handoffs")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["items"]) == 3
    assert all(h["tenant_id"] == tid for h in body["items"])
    # Sorted DESC by requested_at — newest first
    assert body["items"][0]["id"] == hids[-1]
    # Payload is preserved
    assert body["items"][0]["payload"]["customer"] == "Juan"


def test_list_handoffs_filter_by_status(operator_with_handoffs):
    tid, _, email, plain, _, hids = operator_with_handoffs

    async def _resolve_one():
        engine = create_async_engine(get_settings().database_url)
        async with engine.begin() as conn:
            await conn.execute(
                text("UPDATE human_handoffs SET status='resolved' WHERE id = :h"),
                {"h": hids[0]},
            )
        await engine.dispose()

    asyncio.run(_resolve_one())

    client = TestClient(app)
    csrf = _login(client, email, plain)

    open_only = client.get("/api/v1/handoffs?status=open").json()
    assert len(open_only["items"]) == 2

    resolved_only = client.get("/api/v1/handoffs?status=resolved").json()
    assert len(resolved_only["items"]) == 1
    assert resolved_only["items"][0]["id"] == hids[0]


def test_assign_handoff(operator_with_handoffs):
    _, uid, email, plain, _, hids = operator_with_handoffs
    client = TestClient(app)
    csrf = _login(client, email, plain)

    resp = client.post(
        f"/api/v1/handoffs/{hids[0]}/assign",
        json={"user_id": uid},
        headers={"X-CSRF-Token": csrf},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "assigned"
    assert body["assigned_user_id"] == uid


def test_resolve_handoff_records_note(operator_with_handoffs):
    _, _, email, plain, _, hids = operator_with_handoffs
    client = TestClient(app)
    csrf = _login(client, email, plain)

    resp = client.post(
        f"/api/v1/handoffs/{hids[0]}/resolve",
        json={"note": "Cliente atendido por WhatsApp directo"},
        headers={"X-CSRF-Token": csrf},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "resolved"
    assert body["resolved_at"]
    assert body["payload"]["resolution_note"] == "Cliente atendido por WhatsApp directo"


def test_assign_handoff_404_for_other_tenant(operator_with_handoffs):
    """Operator A tries to assign a handoff that belongs to tenant B."""
    other_seed = _seed_with_handoffs(num_handoffs=1)
    other_tid, _, _, _, _, other_hids = other_seed
    try:
        _, uid, email, plain, _, _ = operator_with_handoffs
        client = TestClient(app)
        csrf = _login(client, email, plain)

        resp = client.post(
            f"/api/v1/handoffs/{other_hids[0]}/assign",
            json={"user_id": uid},
            headers={"X-CSRF-Token": csrf},
        )
        assert resp.status_code == 404
    finally:
        _cleanup(other_tid)


def test_intervene_pauses_bot_and_inserts_outbound(operator_with_handoffs):
    _, _, email, plain, conv, _ = operator_with_handoffs
    client = TestClient(app)
    csrf = _login(client, email, plain)

    resp = client.post(
        f"/api/v1/conversations/{conv}/intervene",
        json={"text": "Hola, soy Francisco. Yo te ayudo."},
        headers={"X-CSRF-Token": csrf},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["text"] == "Hola, soy Francisco. Yo te ayudo."

    # bot_paused now True
    detail = client.get(f"/api/v1/conversations/{conv}").json()
    assert detail["bot_paused"] is True

    # Outbound message persisted with delivery_status='queued' so the UI
    # shows a real "encolado" state, not a fake double check.
    msgs = client.get(f"/api/v1/conversations/{conv}/messages").json()
    operator_msg = next(
        (m for m in msgs["items"] if m["text"] == "Hola, soy Francisco. Yo te ayudo."),
        None,
    )
    assert operator_msg is not None
    assert operator_msg["direction"] == "outbound"
    assert operator_msg["delivery_status"] == "queued"


def test_intervene_enqueues_send_outbound(operator_with_handoffs, monkeypatch):
    """Regression for the bug where /intervene persisted the row but never
    actually sent the message to WhatsApp.

    We can't reach a live arq worker from a unit test, so we patch the
    route's `enqueue_outbound` binding and assert it was invoked with an
    OutboundMessage carrying the operator's text + the customer's phone.
    """
    from atendia.api import conversations_routes

    captured: list = []

    async def _fake_enqueue(_redis, msg):
        captured.append(msg)
        return msg.idempotency_key

    class _FakePool:
        async def aclose(self):
            return None

    async def _fake_create_pool(_settings):
        return _FakePool()

    monkeypatch.setattr(conversations_routes, "enqueue_outbound", _fake_enqueue)
    monkeypatch.setattr(conversations_routes, "create_pool", _fake_create_pool)

    _, _, email, plain, conv, _ = operator_with_handoffs
    client = TestClient(app)
    csrf = _login(client, email, plain)

    resp = client.post(
        f"/api/v1/conversations/{conv}/intervene",
        json={"text": "Voy en camino."},
        headers={"X-CSRF-Token": csrf},
    )
    assert resp.status_code == 200, resp.text
    assert len(captured) == 1, "send_outbound should have been enqueued exactly once"
    out_msg = captured[0]
    assert out_msg.text == "Voy en camino."
    assert out_msg.to_phone_e164.startswith("+")
    assert out_msg.metadata.get("source") == "operator"


def test_intervene_404_for_other_tenant(operator_with_handoffs):
    other_seed = _seed_with_handoffs(num_handoffs=1)
    other_tid, _, _, _, other_conv, _ = other_seed
    try:
        _, _, email, plain, _, _ = operator_with_handoffs
        client = TestClient(app)
        csrf = _login(client, email, plain)
        resp = client.post(
            f"/api/v1/conversations/{other_conv}/intervene",
            json={"text": "x"},
            headers={"X-CSRF-Token": csrf},
        )
        assert resp.status_code == 404
    finally:
        _cleanup(other_tid)


def test_resume_bot_flips_flag(operator_with_handoffs):
    _, _, email, plain, conv, _ = operator_with_handoffs
    client = TestClient(app)
    csrf = _login(client, email, plain)

    # Pause first
    client.post(
        f"/api/v1/conversations/{conv}/intervene",
        json={"text": "tomar control"},
        headers={"X-CSRF-Token": csrf},
    )
    assert client.get(f"/api/v1/conversations/{conv}").json()["bot_paused"] is True

    # Resume
    resp = client.post(
        f"/api/v1/conversations/{conv}/resume-bot",
        headers={"X-CSRF-Token": csrf},
    )
    assert resp.status_code == 200
    assert client.get(f"/api/v1/conversations/{conv}").json()["bot_paused"] is False


def test_intervene_empty_text_returns_400(operator_with_handoffs):
    _, _, email, plain, conv, _ = operator_with_handoffs
    client = TestClient(app)
    csrf = _login(client, email, plain)
    resp = client.post(
        f"/api/v1/conversations/{conv}/intervene",
        json={"text": "   "},
        headers={"X-CSRF-Token": csrf},
    )
    assert resp.status_code == 400
