import pytest

from atendia.channels.base import (
    ChannelAdapter,
    DeliveryReceipt,
    InboundMessage,
    OutboundMessage,
)


def test_outbound_message_text_is_valid():
    msg = OutboundMessage(
        tenant_id="dinamomotos",
        to_phone_e164="+5215555550000",
        text="Hola",
        idempotency_key="abc-123",
    )
    assert msg.text == "Hola"
    assert msg.template is None


def test_outbound_message_template_is_valid():
    msg = OutboundMessage(
        tenant_id="dinamomotos",
        to_phone_e164="+5215555550000",
        template={"name": "lead_warm_v2", "language": "es_MX", "components": []},
        idempotency_key="def-456",
    )
    assert msg.template is not None
    assert msg.text is None


def test_outbound_message_requires_text_or_template():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        OutboundMessage(
            tenant_id="x",
            to_phone_e164="+1",
            idempotency_key="z",
        )


def test_outbound_message_rejects_both_text_and_template():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        OutboundMessage(
            tenant_id="x",
            to_phone_e164="+1",
            text="hi",
            template={"name": "x"},
            idempotency_key="z",
        )


def test_channel_adapter_is_abstract():
    with pytest.raises(TypeError):
        ChannelAdapter()  # type: ignore[abstract]


def test_delivery_receipt_minimal():
    r = DeliveryReceipt(
        message_id="local-uuid-x",
        channel_message_id="wamid.HBgL...",
        status="sent",
    )
    assert r.status == "sent"
    assert r.error is None


def test_delivery_receipt_failed_with_error():
    r = DeliveryReceipt(
        message_id="local-uuid-y",
        status="failed",
        error="meta_error_131000: invalid recipient",
    )
    assert r.status == "failed"
    assert r.channel_message_id is None


def test_delivery_receipt_invalid_status_raises():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        DeliveryReceipt(
            message_id="x",
            status="banana",  # type: ignore[arg-type]
        )


def test_inbound_message_minimal():
    m = InboundMessage(
        tenant_id="t",
        from_phone_e164="+521",
        channel_message_id="wamid.x",
        text="hola",
        received_at="1714579200",
    )
    assert m.text == "hola"
    assert m.media_url is None
