"""Tests for DELETE /api/v1/conversations/:id — soft delete."""
from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from atendia.config import get_settings


def _seed_conversation(tid: str) -> str:
    async def _do() -> str:
        engine = create_async_engine(get_settings().database_url)
        async with engine.begin() as conn:
            cust_id = (await conn.execute(
                text("INSERT INTO customers (tenant_id, phone_e164) VALUES (:t, :p) RETURNING id"),
                {"t": tid, "p": f"+521{uuid4().hex[:10]}"},
            )).scalar()
            conv_id = (await conn.execute(
                text("INSERT INTO conversations (tenant_id, customer_id) VALUES (:t, :c) RETURNING id"),
                {"t": tid, "c": cust_id},
            )).scalar()
            await conn.execute(
                text("INSERT INTO conversation_state (conversation_id) VALUES (:c)"),
                {"c": conv_id},
            )
        await engine.dispose()
        return str(conv_id)
    return asyncio.run(_do())


class TestDeleteConversation:
    def test_soft_delete_returns_204(self, client_operator):
        conv_id = _seed_conversation(client_operator.tenant_id)
        resp = client_operator.delete(f"/api/v1/conversations/{conv_id}")
        assert resp.status_code == 204

    def test_deleted_excluded_from_list(self, client_operator):
        conv_id = _seed_conversation(client_operator.tenant_id)
        client_operator.delete(f"/api/v1/conversations/{conv_id}")
        resp = client_operator.get("/api/v1/conversations")
        ids = [c["id"] for c in resp.json()["items"]]
        assert conv_id not in ids

    def test_deleted_returns_404_on_detail(self, client_operator):
        conv_id = _seed_conversation(client_operator.tenant_id)
        client_operator.delete(f"/api/v1/conversations/{conv_id}")
        resp = client_operator.get(f"/api/v1/conversations/{conv_id}")
        assert resp.status_code == 404

    def test_delete_idempotent(self, client_operator):
        conv_id = _seed_conversation(client_operator.tenant_id)
        client_operator.delete(f"/api/v1/conversations/{conv_id}")
        resp = client_operator.delete(f"/api/v1/conversations/{conv_id}")
        assert resp.status_code == 404

    def test_404_cross_tenant(self, client_operator):
        resp = client_operator.delete(f"/api/v1/conversations/{uuid4()}")
        assert resp.status_code == 404
