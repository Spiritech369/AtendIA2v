"""Tests for POST /api/v1/conversations/:id/mark-read."""
from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from atendia.config import get_settings


def _seed_conversation_with_unread(tid: str, unread: int = 3) -> str:
    async def _do() -> str:
        engine = create_async_engine(get_settings().database_url)
        async with engine.begin() as conn:
            cust_id = (await conn.execute(
                text("INSERT INTO customers (tenant_id, phone_e164) VALUES (:t, :p) RETURNING id"),
                {"t": tid, "p": f"+521{uuid4().hex[:10]}"},
            )).scalar()
            conv_id = (await conn.execute(
                text(
                    "INSERT INTO conversations (tenant_id, customer_id, unread_count) "
                    "VALUES (:t, :c, :u) RETURNING id"
                ),
                {"t": tid, "c": cust_id, "u": unread},
            )).scalar()
            await conn.execute(
                text("INSERT INTO conversation_state (conversation_id) VALUES (:c)"),
                {"c": conv_id},
            )
        await engine.dispose()
        return str(conv_id)
    return asyncio.run(_do())


class TestMarkRead:
    def test_resets_to_zero(self, client_operator):
        conv_id = _seed_conversation_with_unread(client_operator.tenant_id, 5)
        resp = client_operator.post(f"/api/v1/conversations/{conv_id}/mark-read")
        assert resp.status_code == 204

    def test_unread_count_is_zero_after(self, client_operator):
        conv_id = _seed_conversation_with_unread(client_operator.tenant_id, 5)
        client_operator.post(f"/api/v1/conversations/{conv_id}/mark-read")
        detail = client_operator.get(f"/api/v1/conversations/{conv_id}")
        assert detail.json()["unread_count"] == 0

    def test_idempotent(self, client_operator):
        conv_id = _seed_conversation_with_unread(client_operator.tenant_id, 0)
        resp = client_operator.post(f"/api/v1/conversations/{conv_id}/mark-read")
        assert resp.status_code == 204

    def test_404_cross_tenant(self, client_operator):
        resp = client_operator.post(f"/api/v1/conversations/{uuid4()}/mark-read")
        assert resp.status_code == 404
