"""Phase 4 T14 — conversations list endpoint."""

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


def _seed(role: str, num_conversations: int) -> tuple[str, str, str, str, list[str]]:
    """Create a tenant + operator/superadmin user + N conversations.

    Returns (tenant_id, user_id, email, password, [conversation_ids]).
    Conversations have staggered last_activity_at so cursor pagination is testable.
    """
    email = f"phase4_t14_{role}_{uuid4().hex[:8]}@dinamo.com"
    plain = "test-password-123"
    hashed = hash_password(plain)

    async def _do() -> tuple[str, str, list[str]]:
        engine = create_async_engine(get_settings().database_url)
        async with engine.begin() as conn:
            tid = (
                await conn.execute(
                    text("INSERT INTO tenants (name) VALUES (:n) RETURNING id"),
                    {"n": f"phase4_t14_tenant_{uuid4().hex[:8]}"},
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
            cids: list[str] = []
            base = datetime(2026, 5, 1, 12, 0, 0, tzinfo=timezone.utc)
            for i in range(num_conversations):
                cust_id = (
                    await conn.execute(
                        text(
                            "INSERT INTO customers (tenant_id, phone_e164, name) "
                            "VALUES (:t, :p, :n) RETURNING id"
                        ),
                        {
                            "t": tid,
                            "p": f"+5215555{1000 + i:04d}{uuid4().hex[:4]}"[:24],
                            "n": f"Cliente {i}",
                        },
                    )
                ).scalar()
                ts = base + timedelta(minutes=i)
                conv_id = (
                    await conn.execute(
                        text(
                            "INSERT INTO conversations "
                            "(tenant_id, customer_id, current_stage, last_activity_at) "
                            "VALUES (:t, :c, 'qualify', :ts) RETURNING id"
                        ),
                        {"t": tid, "c": cust_id, "ts": ts},
                    )
                ).scalar()
                await conn.execute(
                    text("INSERT INTO conversation_state (conversation_id) VALUES (:c)"),
                    {"c": conv_id},
                )
                # Add one outbound message per conversation so last_message_text
                # is populated.
                await conn.execute(
                    text(
                        "INSERT INTO messages (tenant_id, conversation_id, direction, text, sent_at) "
                        "VALUES (:t, :c, 'outbound', :m, :ts)"
                    ),
                    {"t": tid, "c": conv_id, "m": f"Hola {i}", "ts": ts},
                )
                cids.append(str(conv_id))
        await engine.dispose()
        return str(tid), str(uid), cids

    tid, uid, cids = asyncio.run(_do())
    return tid, uid, email, plain, cids


def _cleanup(tid: str) -> None:
    async def _do() -> None:
        engine = create_async_engine(get_settings().database_url)
        async with engine.begin() as conn:
            await conn.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": tid})
        await engine.dispose()

    asyncio.run(_do())


@pytest.fixture
def operator_with_convs() -> Iterator[tuple[str, str, str, str, list[str]]]:
    seed = _seed("operator", num_conversations=5)
    yield seed
    _cleanup(seed[0])


@pytest.fixture
def two_tenants() -> Iterator[
    tuple[tuple[str, str, str, str, list[str]], tuple[str, str, str, str, list[str]]]
]:
    a = _seed("operator", num_conversations=2)
    b = _seed("operator", num_conversations=2)
    yield a, b
    _cleanup(a[0])
    _cleanup(b[0])


def _login(client: TestClient, email: str, password: str) -> str:
    resp = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["csrf_token"]


def test_list_conversations_returns_tenant_scoped_items(operator_with_convs):
    tid, _, email, plain, cids = operator_with_convs
    client = TestClient(app)
    _login(client, email, plain)

    resp = client.get("/api/v1/conversations?limit=10")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "items" in body and "next_cursor" in body
    assert len(body["items"]) == len(cids)
    assert all(c["tenant_id"] == tid for c in body["items"])
    # Sorted DESC by last_activity_at — newest conversation first
    assert body["items"][0]["id"] == cids[-1]
    # last_message preview is set
    assert body["items"][0]["last_message_text"]
    assert body["items"][0]["last_message_direction"] == "outbound"


def test_list_conversations_paginates_via_cursor(operator_with_convs):
    _, _, email, plain, cids = operator_with_convs
    client = TestClient(app)
    _login(client, email, plain)

    page1 = client.get("/api/v1/conversations?limit=2").json()
    assert len(page1["items"]) == 2
    assert page1["next_cursor"]

    page2 = client.get(f"/api/v1/conversations?limit=2&cursor={page1['next_cursor']}").json()
    assert len(page2["items"]) == 2
    # Different rows than page1
    page1_ids = {c["id"] for c in page1["items"]}
    page2_ids = {c["id"] for c in page2["items"]}
    assert not (page1_ids & page2_ids)

    page3 = client.get(f"/api/v1/conversations?limit=2&cursor={page2['next_cursor']}").json()
    assert len(page3["items"]) == 1  # 5 total - 4 = 1
    assert page3["next_cursor"] is None


def test_operator_cannot_see_other_tenants(two_tenants):
    (tid_a, _, email_a, plain_a, cids_a), (tid_b, _, _, _, cids_b) = two_tenants
    client = TestClient(app)
    _login(client, email_a, plain_a)

    resp = client.get("/api/v1/conversations?limit=50")
    assert resp.status_code == 200
    items = resp.json()["items"]
    seen_ids = {c["id"] for c in items}
    assert seen_ids == set(cids_a)
    assert all(c["tenant_id"] == tid_a for c in items)
    assert not (seen_ids & set(cids_b))


def test_operator_cannot_override_tenant_via_query(two_tenants):
    """Operator passes ?tid=other_tenant — current_tenant_id IGNORES it."""
    (tid_a, _, email_a, plain_a, cids_a), (tid_b, _, _, _, _cids_b) = two_tenants
    client = TestClient(app)
    _login(client, email_a, plain_a)

    resp = client.get(f"/api/v1/conversations?tid={tid_b}")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert all(c["tenant_id"] == tid_a for c in items)


def test_invalid_cursor_returns_400(operator_with_convs):
    _, _, email, plain, _ = operator_with_convs
    client = TestClient(app)
    _login(client, email, plain)

    resp = client.get("/api/v1/conversations?cursor=not-base64-at-all")
    assert resp.status_code == 400


def test_unauthenticated_request_returns_401():
    client = TestClient(app)
    resp = client.get("/api/v1/conversations")
    assert resp.status_code == 401


def test_filter_by_status(operator_with_convs):
    tid, _, email, plain, cids = operator_with_convs

    # Manually set one conversation to status='closed'
    async def _close_one() -> None:
        engine = create_async_engine(get_settings().database_url)
        async with engine.begin() as conn:
            await conn.execute(
                text("UPDATE conversations SET status='closed' WHERE id = :c"),
                {"c": cids[0]},
            )
        await engine.dispose()

    asyncio.run(_close_one())

    client = TestClient(app)
    _login(client, email, plain)

    closed = client.get("/api/v1/conversations?status=closed").json()
    assert len(closed["items"]) == 1
    assert closed["items"][0]["id"] == cids[0]

    active = client.get("/api/v1/conversations?status=active").json()
    assert len(active["items"]) == 4


def test_get_conversation_detail_returns_state(operator_with_convs):
    tid, _, email, plain, cids = operator_with_convs
    client = TestClient(app)
    _login(client, email, plain)

    resp = client.get(f"/api/v1/conversations/{cids[0]}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == cids[0]
    assert body["tenant_id"] == tid
    assert body["customer_phone"]
    assert "extracted_data" in body
    assert body["bot_paused"] is False  # default
    assert "current_stage" in body


def test_get_conversation_404_for_other_tenant(two_tenants):
    (tid_a, _, email_a, plain_a, _), (_, _, _, _, cids_b) = two_tenants
    client = TestClient(app)
    _login(client, email_a, plain_a)

    resp = client.get(f"/api/v1/conversations/{cids_b[0]}")
    # 404, not 403 — don't leak existence across tenant boundary.
    assert resp.status_code == 404


def test_list_messages_returns_newest_first(operator_with_convs):
    tid, _, email, plain, cids = operator_with_convs

    async def _add_messages() -> None:
        engine = create_async_engine(get_settings().database_url)
        async with engine.begin() as conn:
            base = datetime(2026, 5, 2, 12, 0, 0, tzinfo=timezone.utc)
            for i in range(3):
                await conn.execute(
                    text(
                        "INSERT INTO messages (tenant_id, conversation_id, direction, text, sent_at, created_at) "
                        "VALUES (:t, :c, :d, :m, :ts, :ts)"
                    ),
                    {
                        "t": tid,
                        "c": cids[0],
                        "d": "inbound" if i % 2 == 0 else "outbound",
                        "m": f"Msg #{i}",
                        "ts": base + timedelta(minutes=i),
                    },
                )
        await engine.dispose()

    asyncio.run(_add_messages())

    client = TestClient(app)
    _login(client, email, plain)

    resp = client.get(f"/api/v1/conversations/{cids[0]}/messages?limit=10")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # Newest first — Msg #2 at the top
    assert body["items"][0]["text"] == "Msg #2"
    # The fixture's "Hola 0" outbound from setup is also there
    texts = [m["text"] for m in body["items"]]
    assert "Hola 0" in texts


def test_list_messages_404_for_other_tenant(two_tenants):
    (_, _, email_a, plain_a, _), (_, _, _, _, cids_b) = two_tenants
    client = TestClient(app)
    _login(client, email_a, plain_a)

    resp = client.get(f"/api/v1/conversations/{cids_b[0]}/messages")
    assert resp.status_code == 404


def test_filter_by_has_pending_handoff(operator_with_convs):
    tid, _, email, plain, cids = operator_with_convs

    async def _open_handoff() -> None:
        engine = create_async_engine(get_settings().database_url)
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO human_handoffs "
                    "(conversation_id, tenant_id, reason, status) "
                    "VALUES (:c, :t, 'op needs help', 'open')"
                ),
                {"c": cids[2], "t": tid},
            )
        await engine.dispose()

    asyncio.run(_open_handoff())

    client = TestClient(app)
    _login(client, email, plain)

    pending = client.get("/api/v1/conversations?has_pending_handoff=true").json()
    assert len(pending["items"]) == 1
    assert pending["items"][0]["id"] == cids[2]
    assert pending["items"][0]["has_pending_handoff"] is True
