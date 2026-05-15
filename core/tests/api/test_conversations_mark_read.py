"""Tests for POST /api/v1/conversations/:id/mark-read."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from atendia.api._auth_helpers import hash_password
from atendia.config import get_settings
from atendia.main import app


def _seed_conversation_with_unread(tid: str, unread: int = 3) -> str:
    async def _do() -> str:
        engine = create_async_engine(get_settings().database_url)
        async with engine.begin() as conn:
            cust_id = (
                await conn.execute(
                    text(
                        "INSERT INTO customers (tenant_id, phone_e164) VALUES (:t, :p) RETURNING id"
                    ),
                    {"t": tid, "p": f"+521{uuid4().hex[:10]}"},
                )
            ).scalar()
            conv_id = (
                await conn.execute(
                    text(
                        "INSERT INTO conversations (tenant_id, customer_id) "
                        "VALUES (:t, :c) RETURNING id"
                    ),
                    {"t": tid, "c": cust_id},
                )
            ).scalar()
            await conn.execute(
                text("INSERT INTO conversation_state (conversation_id) VALUES (:c)"),
                {"c": conv_id},
            )
            base = datetime.now(UTC) - timedelta(minutes=unread + 1)
            for i in range(unread):
                await conn.execute(
                    text(
                        "INSERT INTO messages "
                        "(tenant_id, conversation_id, direction, text, sent_at, created_at) "
                        "VALUES (:t, :c, 'inbound', :txt, :ts, :ts)"
                    ),
                    {
                        "t": tid,
                        "c": conv_id,
                        "txt": f"inbound {i}",
                        "ts": base + timedelta(minutes=i),
                    },
                )
        await engine.dispose()
        return str(conv_id)

    return asyncio.run(_do())


def _seed_second_operator(tid: str) -> tuple[str, str]:
    email = f"mark_read_second_{uuid4().hex[:8]}@dinamo.com"
    password = "test-password-123"

    async def _do() -> None:
        engine = create_async_engine(get_settings().database_url)
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO tenant_users (tenant_id, email, role, password_hash) "
                    "VALUES (:t, :e, 'operator', :h)"
                ),
                {"t": tid, "e": email, "h": hash_password(password)},
            )
        await engine.dispose()

    asyncio.run(_do())
    return email, password


def _insert_inbound(tid: str, conv_id: str, text_value: str = "new inbound") -> None:
    async def _do() -> None:
        engine = create_async_engine(get_settings().database_url)
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO messages "
                    "(tenant_id, conversation_id, direction, text, sent_at, created_at) "
                    "VALUES (:t, :c, 'inbound', :txt, :ts, :ts)"
                ),
                {"t": tid, "c": conv_id, "txt": text_value, "ts": datetime.now(UTC)},
            )
        await engine.dispose()

    asyncio.run(_do())


def _login(email: str, password: str) -> TestClient:
    client = TestClient(app)
    resp = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200
    client.headers["X-CSRF-Token"] = resp.json()["csrf_token"]
    return client


class TestMarkRead:
    def test_resets_to_zero(self, client_operator):
        conv_id = _seed_conversation_with_unread(client_operator.tenant_id, 5)
        resp = client_operator.post(f"/api/v1/conversations/{conv_id}/mark-read")
        assert resp.status_code == 204

    def test_unread_count_is_zero_after(self, client_operator):
        conv_id = _seed_conversation_with_unread(client_operator.tenant_id, 5)
        before = client_operator.get(f"/api/v1/conversations/{conv_id}")
        assert before.json()["unread_count"] == 5
        client_operator.post(f"/api/v1/conversations/{conv_id}/mark-read")
        detail = client_operator.get(f"/api/v1/conversations/{conv_id}")
        assert detail.json()["unread_count"] == 0

    def test_mark_read_is_per_user(self, client_operator):
        conv_id = _seed_conversation_with_unread(client_operator.tenant_id, 4)
        second_email, second_password = _seed_second_operator(client_operator.tenant_id)
        second_client = _login(second_email, second_password)

        client_operator.post(f"/api/v1/conversations/{conv_id}/mark-read")

        first_detail = client_operator.get(f"/api/v1/conversations/{conv_id}")
        second_detail = second_client.get(f"/api/v1/conversations/{conv_id}")
        assert first_detail.json()["unread_count"] == 0
        assert second_detail.json()["unread_count"] == 4

    def test_new_inbound_after_mark_read_is_unread(self, client_operator):
        conv_id = _seed_conversation_with_unread(client_operator.tenant_id, 2)
        client_operator.post(f"/api/v1/conversations/{conv_id}/mark-read")

        _insert_inbound(client_operator.tenant_id, conv_id)

        detail = client_operator.get(f"/api/v1/conversations/{conv_id}")
        assert detail.json()["unread_count"] == 1

    def test_idempotent(self, client_operator):
        conv_id = _seed_conversation_with_unread(client_operator.tenant_id, 0)
        resp = client_operator.post(f"/api/v1/conversations/{conv_id}/mark-read")
        assert resp.status_code == 204

    def test_404_cross_tenant(self, client_operator):
        resp = client_operator.post(f"/api/v1/conversations/{uuid4()}/mark-read")
        assert resp.status_code == 404
