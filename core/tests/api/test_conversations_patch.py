"""Tests for PATCH /api/v1/conversations/:id — partial update."""
from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from atendia.api._auth_helpers import hash_password
from atendia.config import get_settings


def _ensure_pipeline(tid: str, stages: list[str] | None = None) -> None:
    async def _do() -> None:
        engine = create_async_engine(get_settings().database_url)
        async with engine.begin() as conn:
            version = (await conn.execute(
                text(
                    "SELECT COALESCE(MAX(version), 0) + 1 "
                    "FROM tenant_pipelines WHERE tenant_id = :t"
                ),
                {"t": tid},
            )).scalar()
            await conn.execute(
                text("UPDATE tenant_pipelines SET active = false WHERE tenant_id = :t"),
                {"t": tid},
            )
            await conn.execute(
                text(
                    "INSERT INTO tenant_pipelines (tenant_id, version, definition, active) "
                    "VALUES (:t, :v, CAST(:d AS JSONB), true)"
                ),
                {
                    "t": tid,
                    "v": version,
                    "d": json.dumps(
                        {
                            "version": 1,
                            "stages": [{"id": s} for s in (stages or ["greeting", "quoted"])],
                            "fallback": "fallback",
                        }
                    ),
                },
            )
        await engine.dispose()
    asyncio.run(_do())


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
                text(
                    "INSERT INTO conversations (tenant_id, customer_id) "
                    "VALUES (:t, :c) RETURNING id"
                ),
                {"t": tid, "c": cust_id},
            )).scalar()
            await conn.execute(
                text("INSERT INTO conversation_state (conversation_id) VALUES (:c)"),
                {"c": conv_id},
            )
        await engine.dispose()
        return str(conv_id)
    return asyncio.run(_do())


def _seed_user(tid: str, role: str = "operator") -> str:
    async def _do() -> str:
        engine = create_async_engine(get_settings().database_url)
        async with engine.begin() as conn:
            uid = (await conn.execute(
                text(
                    "INSERT INTO tenant_users (tenant_id, email, role, password_hash) "
                    "VALUES (:t, :e, :r, :h) RETURNING id"
                ),
                {
                    "t": tid,
                    "e": f"patch_assignee_{uuid4().hex[:8]}@dinamo.com",
                    "r": role,
                    "h": hash_password("test-password-123"),
                },
            )).scalar()
        await engine.dispose()
        return str(uid)
    return asyncio.run(_do())


def _cleanup_tenant(tid: str) -> None:
    async def _do() -> None:
        engine = create_async_engine(get_settings().database_url)
        async with engine.begin() as conn:
            await conn.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": tid})
        await engine.dispose()
    asyncio.run(_do())


def _seed_other_tenant_user() -> tuple[str, str]:
    async def _do() -> tuple[str, str]:
        engine = create_async_engine(get_settings().database_url)
        async with engine.begin() as conn:
            tid = (await conn.execute(
                text("INSERT INTO tenants (name) VALUES (:n) RETURNING id"),
                {"n": f"other_patch_{uuid4().hex[:8]}"},
            )).scalar()
            uid = (await conn.execute(
                text(
                    "INSERT INTO tenant_users (tenant_id, email, role, password_hash) "
                    "VALUES (:t, :e, 'operator', :h) RETURNING id"
                ),
                {
                    "t": tid,
                    "e": f"other_patch_{uuid4().hex[:8]}@dinamo.com",
                    "h": hash_password("test-password-123"),
                },
            )).scalar()
        await engine.dispose()
        return str(tid), str(uid)
    return asyncio.run(_do())


def _stage_entered_at(conv_id: str) -> str:
    async def _do() -> str:
        engine = create_async_engine(get_settings().database_url)
        async with engine.begin() as conn:
            value = (await conn.execute(
                text(
                    "SELECT stage_entered_at FROM conversation_state "
                    "WHERE conversation_id = :c"
                ),
                {"c": conv_id},
            )).scalar()
        await engine.dispose()
        return value.isoformat()
    return asyncio.run(_do())


def _set_stage_entered_at(conv_id: str, value: datetime) -> None:
    async def _do() -> None:
        engine = create_async_engine(get_settings().database_url)
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "UPDATE conversation_state SET stage_entered_at = :v "
                    "WHERE conversation_id = :c"
                ),
                {"c": conv_id, "v": value},
            )
        await engine.dispose()
    asyncio.run(_do())


class TestPatchConversation:
    def test_update_stage(self, client_operator):
        _ensure_pipeline(client_operator.tenant_id, ["greeting", "quoted"])
        conv_id = _seed_conversation(client_operator.tenant_id)
        resp = client_operator.patch(
            f"/api/v1/conversations/{conv_id}",
            json={"current_stage": "quoted"},
        )
        assert resp.status_code == 200
        assert resp.json()["current_stage"] == "quoted"

    def test_update_stage_requires_active_pipeline(self, client_operator):
        conv_id = _seed_conversation(client_operator.tenant_id)
        resp = client_operator.patch(
            f"/api/v1/conversations/{conv_id}",
            json={"current_stage": "quoted"},
        )
        assert resp.status_code == 409

    def test_update_stage_rejects_unknown_pipeline_stage(self, client_operator):
        _ensure_pipeline(client_operator.tenant_id, ["greeting", "quoted"])
        conv_id = _seed_conversation(client_operator.tenant_id)
        resp = client_operator.patch(
            f"/api/v1/conversations/{conv_id}",
            json={"current_stage": "closed_won"},
        )
        assert resp.status_code == 400

    def test_update_stage_refreshes_stage_entered_at(self, client_operator):
        _ensure_pipeline(client_operator.tenant_id, ["greeting", "quoted"])
        conv_id = _seed_conversation(client_operator.tenant_id)
        _set_stage_entered_at(conv_id, datetime(2026, 1, 1, tzinfo=UTC))
        before = _stage_entered_at(conv_id)
        resp = client_operator.patch(
            f"/api/v1/conversations/{conv_id}",
            json={"current_stage": "quoted"},
        )
        assert resp.status_code == 200
        after = _stage_entered_at(conv_id)
        assert after != before

    def test_update_tags(self, client_operator):
        conv_id = _seed_conversation(client_operator.tenant_id)
        resp = client_operator.patch(
            f"/api/v1/conversations/{conv_id}",
            json={"tags": [" VIP ", "urgent", "vip"]},
        )
        assert resp.status_code == 200
        assert resp.json()["tags"] == ["vip", "urgent"]

    def test_reject_too_many_tags(self, client_operator):
        conv_id = _seed_conversation(client_operator.tenant_id)
        resp = client_operator.patch(
            f"/api/v1/conversations/{conv_id}",
            json={"tags": [f"tag{i}" for i in range(11)]},
        )
        assert resp.status_code == 422

    def test_assign_user(self, client_operator):
        conv_id = _seed_conversation(client_operator.tenant_id)
        resp = client_operator.patch(
            f"/api/v1/conversations/{conv_id}",
            json={"assigned_user_id": client_operator.user_id},
        )
        assert resp.status_code == 200
        assert resp.json()["assigned_user_id"] == client_operator.user_id

    def test_assign_other_same_tenant_user(self, client_operator):
        assignee_id = _seed_user(client_operator.tenant_id)
        conv_id = _seed_conversation(client_operator.tenant_id)
        resp = client_operator.patch(
            f"/api/v1/conversations/{conv_id}",
            json={"assigned_user_id": assignee_id},
        )
        assert resp.status_code == 200
        assert resp.json()["assigned_user_id"] == assignee_id

    def test_reject_cross_tenant_assignee(self, client_operator):
        other_tid, other_user_id = _seed_other_tenant_user()
        conv_id = _seed_conversation(client_operator.tenant_id)
        try:
            resp = client_operator.patch(
                f"/api/v1/conversations/{conv_id}",
                json={"assigned_user_id": other_user_id},
            )
            assert resp.status_code == 404
        finally:
            _cleanup_tenant(other_tid)

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

    def test_unknown_field_is_rejected(self, client_operator):
        conv_id = _seed_conversation(client_operator.tenant_id)
        resp = client_operator.patch(
            f"/api/v1/conversations/{conv_id}",
            json={"deleted_at": "2026-05-08T00:00:00Z"},
        )
        assert resp.status_code == 422

    def test_unauthenticated(self, client):
        """Unauthenticated PATCH — CSRF middleware fires before auth, so 403."""
        resp = client.patch(
            f"/api/v1/conversations/{uuid4()}",
            json={"current_stage": "quoted"},
        )
        assert resp.status_code in (401, 403)
