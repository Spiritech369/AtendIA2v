import json

import httpx
import pytest
import respx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from atendia.config import get_settings
from atendia.queue.worker import send_outbound


@pytest.fixture(autouse=True)
def set_meta_creds(monkeypatch):
    monkeypatch.setenv("ATENDIA_V2_META_APP_SECRET", "secret_t17")
    monkeypatch.setenv("ATENDIA_V2_META_ACCESS_TOKEN", "TOKEN_T17")
    monkeypatch.setenv("ATENDIA_V2_META_API_VERSION", "v21.0")
    monkeypatch.setenv("ATENDIA_V2_META_BASE_URL", "https://graph.facebook.com")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def setup_tenant():
    import asyncio

    async def _setup():
        engine = create_async_engine(get_settings().database_url)
        async with engine.begin() as conn:
            tid = (await conn.execute(
                text("INSERT INTO tenants (name, config) VALUES (:n, :c\\:\\:jsonb) RETURNING id"),
                {
                    "n": "test_t17_worker",
                    "c": json.dumps({"meta": {"phone_number_id": "PID_T17", "verify_token": "vt_t17"}}),
                },
            )).scalar()
        await engine.dispose()
        return tid

    async def _cleanup(tid):
        engine = create_async_engine(get_settings().database_url)
        async with engine.begin() as conn:
            await conn.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": tid})
        await engine.dispose()

    tid = asyncio.run(_setup())
    yield tid
    asyncio.run(_cleanup(tid))


async def _read_messages(tid):
    engine = create_async_engine(get_settings().database_url)
    async with engine.begin() as conn:
        rows = (await conn.execute(
            text("SELECT direction, text, channel_message_id, delivery_status "
                 "FROM messages WHERE tenant_id = :t ORDER BY sent_at"),
            {"t": tid},
        )).fetchall()
    await engine.dispose()
    return rows


@pytest.mark.asyncio
@respx.mock
async def test_send_outbound_persists_outbound_row_on_success(setup_tenant):
    tid = setup_tenant
    respx.post(
        "https://graph.facebook.com/v21.0/PID_T17/messages"
    ).mock(
        return_value=httpx.Response(
            200,
            json={"messaging_product": "whatsapp", "messages": [{"id": "wamid.OUT_T17_A"}]},
        )
    )

    result = await send_outbound(
        {},
        {
            "tenant_id": str(tid),
            "to_phone_e164": "+5215555550170",
            "text": "hola desde el worker",
            "idempotency_key": "test_t17_idem_a",
            "metadata": {},
        },
    )

    assert result["status"] == "sent"
    assert "message_id" in result

    rows = await _read_messages(tid)
    assert len(rows) == 1
    direction, txt, cmid, status = rows[0]
    assert direction == "outbound"
    assert txt == "hola desde el worker"
    assert cmid == "wamid.OUT_T17_A"
    assert status == "sent"


@pytest.mark.asyncio
@respx.mock
async def test_send_outbound_idempotency_key_does_not_resend(setup_tenant):
    tid = setup_tenant
    route = respx.post(
        "https://graph.facebook.com/v21.0/PID_T17/messages"
    ).mock(
        return_value=httpx.Response(
            200,
            json={"messaging_product": "whatsapp", "messages": [{"id": "wamid.OUT_T17_IDEM"}]},
        )
    )
    msg = {
        "tenant_id": str(tid),
        "to_phone_e164": "+5215555550171",
        "text": "solo una vez",
        "idempotency_key": "test_t17_idem_once",
        "metadata": {},
    }

    first = await send_outbound({}, msg)
    second = await send_outbound({}, msg)

    assert first["status"] == "sent"
    assert second["status"] == "sent"
    assert route.call_count == 1
    assert len(await _read_messages(tid)) == 1


@pytest.mark.asyncio
@respx.mock
async def test_send_outbound_persists_failed_row_when_meta_returns_error(setup_tenant):
    tid = setup_tenant
    respx.post(
        "https://graph.facebook.com/v21.0/PID_T17/messages"
    ).mock(
        return_value=httpx.Response(
            400,
            json={"error": {"code": 131000, "message": "Recipient not on WhatsApp"}},
        )
    )

    result = await send_outbound(
        {},
        {
            "tenant_id": str(tid),
            "to_phone_e164": "+5215555550999",
            "text": "destino inválido",
            "idempotency_key": "test_t17_idem_b",
            "metadata": {},
        },
    )

    assert result["status"] == "failed"

    rows = await _read_messages(tid)
    assert len(rows) == 1
    _, _, _, status = rows[0]
    assert status == "failed"
