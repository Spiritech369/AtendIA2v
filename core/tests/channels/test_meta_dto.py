import pytest

from atendia.channels.meta_dto import (
    MetaInboundWebhook,
    MetaInboundMessage,
    MetaStatusCallback,
)


def test_parses_real_meta_text_message_payload():
    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "WABA_ID",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": "5215555000000",
                                "phone_number_id": "PHONE_NUMBER_ID",
                            },
                            "contacts": [
                                {
                                    "profile": {"name": "Juan"},
                                    "wa_id": "5215555550001",
                                }
                            ],
                            "messages": [
                                {
                                    "from": "5215555550001",
                                    "id": "wamid.HBgLNTIxNTU1NTU1NTAwMDEVAgASGBQzQUUz",
                                    "timestamp": "1714579200",
                                    "text": {"body": "hola"},
                                    "type": "text",
                                }
                            ],
                        },
                    }
                ],
            }
        ],
    }
    parsed = MetaInboundWebhook.model_validate(payload)
    assert parsed.object == "whatsapp_business_account"
    assert len(parsed.entry) == 1
    change = parsed.entry[0].changes[0]
    assert change.field == "messages"
    assert change.value.messages is not None
    assert change.value.messages[0].text.body == "hola"
    assert change.value.messages[0].id == "wamid.HBgLNTIxNTU1NTU1NTAwMDEVAgASGBQzQUUz"
    # `from` is reserved in Python; we expose it as `from_`
    assert change.value.messages[0].from_ == "5215555550001"


def test_parses_status_callback():
    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "WABA_ID",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": "5215555000000",
                                "phone_number_id": "PHONE_NUMBER_ID",
                            },
                            "statuses": [
                                {
                                    "id": "wamid.HBgL...",
                                    "status": "delivered",
                                    "timestamp": "1714579260",
                                    "recipient_id": "5215555550001",
                                }
                            ],
                        },
                    }
                ],
            }
        ],
    }
    parsed = MetaInboundWebhook.model_validate(payload)
    statuses = parsed.entry[0].changes[0].value.statuses
    assert statuses is not None
    assert statuses[0].status == "delivered"
    assert statuses[0].id == "wamid.HBgL..."


def test_parses_payload_with_neither_messages_nor_statuses():
    """Some webhooks have just system events; `messages` and `statuses` both None."""
    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "WABA_ID",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {"display_phone_number": "x", "phone_number_id": "y"},
                        },
                    }
                ],
            }
        ],
    }
    parsed = MetaInboundWebhook.model_validate(payload)
    val = parsed.entry[0].changes[0].value
    assert val.messages is None
    assert val.statuses is None


def test_invalid_status_value_raises():
    from pydantic import ValidationError

    payload = {
        "id": "wamid.x",
        "status": "weird_status_not_supported",
        "timestamp": "1",
        "recipient_id": "5215",
    }
    with pytest.raises(ValidationError):
        MetaStatusCallback.model_validate(payload)
