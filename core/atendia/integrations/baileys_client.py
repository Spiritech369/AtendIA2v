"""HTTP client for the Baileys sidecar microservice.

Thin wrapper over httpx. Keeps the auth header + base URL in one place
and surfaces typed responses to the FastAPI routes. The sidecar protocol
is documented in `core/baileys-bridge/README.md`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

import httpx

from atendia.config import get_settings


class BaileysBridgeUnavailable(RuntimeError):
    """Raised when the sidecar HTTP call fails (timeout, 5xx, network)."""


@dataclass(frozen=True)
class BaileysStatus:
    status: str  # disconnected | connecting | qr_pending | connected | error
    phone: str | None
    last_status_at: str
    reason: str | None


@dataclass(frozen=True)
class BaileysSendResult:
    message_id: str | None
    sent_at: str


def _client() -> httpx.AsyncClient:
    settings = get_settings()
    return httpx.AsyncClient(
        base_url=settings.baileys_bridge_url,
        timeout=settings.baileys_timeout_s,
        headers={"X-Internal-Token": settings.baileys_internal_token},
    )


def _to_status(data: dict[str, Any]) -> BaileysStatus:
    return BaileysStatus(
        status=data.get("status", "disconnected"),
        phone=data.get("phone"),
        last_status_at=data.get("last_status_at", ""),
        reason=data.get("reason"),
    )


async def get_status(tenant_id: UUID) -> BaileysStatus:
    async with _client() as c:
        try:
            r = await c.get(f"/sessions/{tenant_id}/status")
            r.raise_for_status()
        except (httpx.HTTPError, httpx.RequestError) as exc:
            raise BaileysBridgeUnavailable(str(exc)) from exc
        return _to_status(r.json())


async def start_session(tenant_id: UUID) -> BaileysStatus:
    async with _client() as c:
        try:
            r = await c.post(f"/sessions/{tenant_id}/connect")
            r.raise_for_status()
        except (httpx.HTTPError, httpx.RequestError) as exc:
            raise BaileysBridgeUnavailable(str(exc)) from exc
        return _to_status(r.json())


async def stop_session(tenant_id: UUID) -> BaileysStatus:
    async with _client() as c:
        try:
            r = await c.post(f"/sessions/{tenant_id}/disconnect")
            r.raise_for_status()
        except (httpx.HTTPError, httpx.RequestError) as exc:
            raise BaileysBridgeUnavailable(str(exc)) from exc
        return _to_status(r.json())


async def get_qr(tenant_id: UUID) -> str | None:
    """Returns the data:image/png;base64 QR or None if not pending."""
    async with _client() as c:
        try:
            r = await c.get(f"/sessions/{tenant_id}/qr")
            r.raise_for_status()
        except (httpx.HTTPError, httpx.RequestError) as exc:
            raise BaileysBridgeUnavailable(str(exc)) from exc
        return r.json().get("qr")


async def send_text(tenant_id: UUID, to_phone: str, text: str) -> BaileysSendResult:
    async with _client() as c:
        try:
            r = await c.post(
                f"/sessions/{tenant_id}/send",
                json={"to_phone": to_phone, "text": text},
            )
            r.raise_for_status()
        except (httpx.HTTPError, httpx.RequestError) as exc:
            raise BaileysBridgeUnavailable(str(exc)) from exc
        data = r.json()
        return BaileysSendResult(
            message_id=data.get("message_id"),
            sent_at=data.get("sent_at", ""),
        )
