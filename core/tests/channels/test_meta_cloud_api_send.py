import httpx
import pytest
import respx

from atendia.channels.base import OutboundMessage
from atendia.channels.meta_cloud_api import MetaCloudAPIAdapter


@pytest.fixture
def adapter():
    return MetaCloudAPIAdapter(
        access_token="TEST_TOKEN",
        app_secret="TEST_SECRET",
        api_version="v21.0",
        base_url="https://graph.facebook.com",
    )


@pytest.mark.asyncio
@respx.mock
async def test_send_text_message_returns_delivery_receipt(adapter):
    route = respx.post(
        "https://graph.facebook.com/v21.0/PHONE_ID/messages"
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "messaging_product": "whatsapp",
                "contacts": [{"input": "+5215555550001", "wa_id": "5215555550001"}],
                "messages": [{"id": "wamid.HBgL_NEW_ID"}],
            },
        )
    )

    msg = OutboundMessage(
        tenant_id="t1",
        to_phone_e164="+5215555550001",
        text="Hola desde el bot",
        idempotency_key="key-001",
    )
    receipt = await adapter.send(msg, phone_number_id="PHONE_ID", message_id="local-uuid-1")
    assert route.called
    assert receipt.status == "sent"
    assert receipt.channel_message_id == "wamid.HBgL_NEW_ID"
    assert receipt.message_id == "local-uuid-1"

    # Verify request body shape
    sent = route.calls.last.request
    body = sent.read().decode()
    assert "Hola desde el bot" in body
    assert "5215555550001" in body
    assert sent.headers["Authorization"] == "Bearer TEST_TOKEN"


@pytest.mark.asyncio
@respx.mock
async def test_send_text_message_returns_failed_on_meta_error(adapter):
    respx.post(
        "https://graph.facebook.com/v21.0/PHONE_ID/messages"
    ).mock(
        return_value=httpx.Response(
            400,
            json={"error": {"code": 131000, "message": "Recipient phone not on WhatsApp"}},
        )
    )

    msg = OutboundMessage(
        tenant_id="t1",
        to_phone_e164="+5215555550999",
        text="bad recipient",
        idempotency_key="key-002",
    )
    receipt = await adapter.send(msg, phone_number_id="PHONE_ID", message_id="local-uuid-2")
    assert receipt.status == "failed"
    assert "131000" in (receipt.error or "")


@pytest.mark.asyncio
@respx.mock
async def test_send_template_message(adapter):
    respx.post(
        "https://graph.facebook.com/v21.0/PHONE_ID/messages"
    ).mock(
        return_value=httpx.Response(
            200,
            json={"messaging_product": "whatsapp", "messages": [{"id": "wamid.TPL"}]},
        )
    )

    msg = OutboundMessage(
        tenant_id="t1",
        to_phone_e164="+5215555550001",
        template={"name": "lead_warm_v2", "language": {"code": "es_MX"}, "components": []},
        idempotency_key="tpl-001",
    )
    receipt = await adapter.send(msg, phone_number_id="PHONE_ID", message_id="local-uuid-tpl")
    assert receipt.status == "sent"
    assert receipt.channel_message_id == "wamid.TPL"


@pytest.mark.asyncio
@respx.mock
async def test_send_returns_failed_on_transport_error(adapter):
    respx.post(
        "https://graph.facebook.com/v21.0/PHONE_ID/messages"
    ).mock(side_effect=httpx.ConnectError("connection refused"))

    msg = OutboundMessage(
        tenant_id="t1",
        to_phone_e164="+5215555550001",
        text="hello",
        idempotency_key="key-net",
    )
    receipt = await adapter.send(msg, phone_number_id="PHONE_ID", message_id="local-uuid-net")
    assert receipt.status == "failed"
    assert "transport_error" in (receipt.error or "")


@pytest.mark.asyncio
@respx.mock
async def test_send_returns_failed_when_response_lacks_message_id(adapter):
    """Meta returned 200 but no `messages[0].id` — treat as failed."""
    respx.post(
        "https://graph.facebook.com/v21.0/PHONE_ID/messages"
    ).mock(
        return_value=httpx.Response(200, json={"messaging_product": "whatsapp", "messages": []})
    )

    msg = OutboundMessage(
        tenant_id="t1",
        to_phone_e164="+5215555550001",
        text="hello",
        idempotency_key="key-empty",
    )
    receipt = await adapter.send(msg, phone_number_id="PHONE_ID", message_id="local-uuid-empty")
    assert receipt.status == "failed"
    assert "no_message_id_in_response" in (receipt.error or "")
