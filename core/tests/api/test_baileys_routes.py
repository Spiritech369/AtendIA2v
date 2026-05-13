"""Tests for /api/v1/integrations/baileys/* + /api/v1/internal/baileys/inbound.

Sidecar HTTP calls are mocked via monkeypatching baileys_client module.
"""
from __future__ import annotations

import asyncio
from collections.abc import Iterator
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from atendia.config import get_settings
from atendia.integrations import baileys_client
from atendia.integrations.baileys_client import BaileysSendResult, BaileysStatus
from atendia.main import app


def _clean(tenant_id: str) -> None:
    async def _do() -> None:
        engine = create_async_engine(get_settings().database_url)
        async with engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM tenant_baileys_config WHERE tenant_id = :t"),
                {"t": tenant_id},
            )
        await engine.dispose()

    asyncio.run(_do())


@pytest.fixture
def mock_sidecar(monkeypatch):
    """Replace baileys_client functions with deterministic stubs.

    Yields a dict whose values can be tweaked per-test.
    """
    state: dict = {
        "status": "disconnected",
        "phone": None,
        "qr": None,
    }

    async def fake_get_status(tid: UUID) -> BaileysStatus:
        return BaileysStatus(
            status=state["status"],
            phone=state["phone"],
            last_status_at="2026-05-13T00:00:00Z",
            reason=None,
        )

    async def fake_start(tid: UUID) -> BaileysStatus:
        state["status"] = "qr_pending"
        return await fake_get_status(tid)

    async def fake_stop(tid: UUID) -> BaileysStatus:
        state["status"] = "disconnected"
        state["phone"] = None
        return await fake_get_status(tid)

    async def fake_qr(tid: UUID) -> str | None:
        return state["qr"]

    async def fake_send(tid: UUID, to: str, txt: str) -> BaileysSendResult:
        return BaileysSendResult(message_id="m-test", sent_at="2026-05-13T00:00:00Z")

    monkeypatch.setattr(baileys_client, "get_status", fake_get_status)
    monkeypatch.setattr(baileys_client, "start_session", fake_start)
    monkeypatch.setattr(baileys_client, "stop_session", fake_stop)
    monkeypatch.setattr(baileys_client, "get_qr", fake_qr)
    monkeypatch.setattr(baileys_client, "send_text", fake_send)

    yield state


def test_status_persists_to_db(client_operator, mock_sidecar):
    mock_sidecar["status"] = "connected"
    mock_sidecar["phone"] = "5215551234567"

    resp = client_operator.get("/api/v1/integrations/baileys/status")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "connected"
    assert body["phone"] == "5215551234567"
    assert body["prefer_over_meta"] is False

    _clean(client_operator.tenant_id)


def test_connect_requires_tenant_admin(client_operator, mock_sidecar):
    resp = client_operator.post("/api/v1/integrations/baileys/connect")
    assert resp.status_code == 403


def test_connect_as_admin_starts_session(client_tenant_admin, mock_sidecar):
    resp = client_tenant_admin.post("/api/v1/integrations/baileys/connect")
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "qr_pending"

    _clean(client_tenant_admin.tenant_id)


def test_qr_returns_data_url_when_pending(client_operator, mock_sidecar):
    mock_sidecar["status"] = "qr_pending"
    mock_sidecar["qr"] = "data:image/png;base64,abc"

    resp = client_operator.get("/api/v1/integrations/baileys/qr")
    assert resp.status_code == 200
    assert resp.json()["qr"] == "data:image/png;base64,abc"


def test_disconnect_requires_tenant_admin(client_operator, mock_sidecar):
    resp = client_operator.post("/api/v1/integrations/baileys/disconnect")
    assert resp.status_code == 403


def test_preference_toggle_persists(client_tenant_admin, mock_sidecar):
    # First connect so a row exists
    client_tenant_admin.post("/api/v1/integrations/baileys/connect")
    resp = client_tenant_admin.patch(
        "/api/v1/integrations/baileys/preference",
        json={"prefer_over_meta": True},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["prefer_over_meta"] is True

    _clean(client_tenant_admin.tenant_id)


def test_internal_inbound_rejects_without_token(client_tenant_admin):
    body = {
        "tenant_id": client_tenant_admin.tenant_id,
        "from_phone": "5215551234567",
        "text": "hola",
        "ts": 1700000000000,
        "message_id": "wa-msg-1",
    }
    resp = client_tenant_admin.post("/api/v1/internal/baileys/inbound", json=body)
    assert resp.status_code == 403


def test_internal_inbound_creates_message(client_tenant_admin):
    settings = get_settings()
    body = {
        "tenant_id": client_tenant_admin.tenant_id,
        "from_phone": "5215557654321",
        "text": "hola desde baileys",
        "ts": 1700000000000,
        "message_id": f"wa-{uuid4().hex[:8]}",
    }
    resp = client_tenant_admin.post(
        "/api/v1/internal/baileys/inbound",
        json=body,
        headers={"X-Internal-Token": settings.baileys_internal_token},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "ok"
    assert "conversation_id" in resp.json()


def test_internal_inbound_deduplicates(client_tenant_admin):
    settings = get_settings()
    body = {
        "tenant_id": client_tenant_admin.tenant_id,
        "from_phone": "5215557654322",
        "text": "duplicado",
        "ts": 1700000000000,
        "message_id": f"wa-dup-{uuid4().hex[:8]}",
    }
    headers = {"X-Internal-Token": settings.baileys_internal_token}
    r1 = client_tenant_admin.post("/api/v1/internal/baileys/inbound", json=body, headers=headers)
    r2 = client_tenant_admin.post("/api/v1/internal/baileys/inbound", json=body, headers=headers)
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r2.json()["status"] == "duplicate"
