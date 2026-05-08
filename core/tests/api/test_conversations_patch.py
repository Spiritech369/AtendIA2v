"""Tests for PATCH /api/v1/conversations/:id — partial update."""
from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from atendia.config import get_settings


def _seed_conversation(tid: str) -> str:
    """Create a customer + conversation, return conversation_id."""
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


class TestPatchConversation:
    def test_update_stage(self, client_operator):
        conv_id = _seed_conversation(client_operator.tenant_id)
        resp = client_operator.patch(
            f"/api/v1/conversations/{conv_id}",
            json={"current_stage": "quoted"},
        )
        assert resp.status_code == 200
        assert resp.json()["current_stage"] == "quoted"

    def test_update_tags(self, client_operator):
        conv_id = _seed_conversation(client_operator.tenant_id)
        resp = client_operator.patch(
            f"/api/v1/conversations/{conv_id}",
            json={"tags": ["vip", "urgent"]},
        )
        assert resp.status_code == 200
        assert resp.json()["tags"] == ["vip", "urgent"]

    def test_assign_user(self, client_operator):
        conv_id = _seed_conversation(client_operator.tenant_id)
        resp = client_operator.patch(
            f"/api/v1/conversations/{conv_id}",
            json={"assigned_user_id": client_operator.user_id},
        )
        assert resp.status_code == 200
        assert resp.json()["assigned_user_id"] == client_operator.user_id

    def test_unassign_user(self, client_operator):
        conv_id = _seed_conversation(client_operator.tenant_id)
        # First assign
        client_operator.patch(
            f"/api/v1/conversations/{conv_id}",
            json={"assigned_user_id": client_operator.user_id},
        )
        # Then unassign
        resp = client_operator.patch(
            f"/api/v1/conversations/{conv_id}",
            json={"assigned_user_id": None},
        )
        assert resp.status_code == 200
        assert resp.json()["assigned_user_id"] is None

    def test_404_cross_tenant(self, client_operator):
        fake_id = str(uuid4())
        resp = client_operator.patch(
            f"/api/v1/conversations/{fake_id}",
            json={"current_stage": "quoted"},
        )
        assert resp.status_code == 404

    def test_empty_body_is_noop(self, client_operator):
        conv_id = _seed_conversation(client_operator.tenant_id)
        resp = client_operator.patch(
            f"/api/v1/conversations/{conv_id}",
            json={},
        )
        assert resp.status_code == 200

    def test_unauthenticated(self, client):
        """Unauthenticated PATCH — CSRF middleware fires before auth, so 403."""
        resp = client.patch(
            f"/api/v1/conversations/{uuid4()}",
            json={"current_stage": "quoted"},
        )
        assert resp.status_code in (401, 403)
