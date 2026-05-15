import pytest

from atendia.channels.meta_cloud_api import MetaCloudAPIAdapter


@pytest.fixture
def adapter():
    return MetaCloudAPIAdapter(
        access_token="x",
        app_secret="y",
        api_version="v21.0",
        base_url="https://graph.facebook.com",
    )


def test_parse_webhook_extracts_text_messages(adapter):
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
                            "messages": [
                                {
                                    "from": "5215555550001",
                                    "id": "wamid.HBgL_X",
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
    messages = adapter.parse_webhook(payload, tenant_id="dinamomotos")
    assert len(messages) == 1
    m = messages[0]
    assert m.tenant_id == "dinamomotos"
    assert m.from_phone_e164 == "+5215555550001"
    assert m.channel_message_id == "wamid.HBgL_X"
    assert m.text == "hola"
    assert m.received_at == "1714579200"


def test_parse_webhook_returns_empty_for_status_only_payload(adapter):
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
                            "statuses": [
                                {
                                    "id": "wamid.x",
                                    "status": "delivered",
                                    "timestamp": "1",
                                    "recipient_id": "5215",
                                }
                            ],
                        },
                    }
                ],
            }
        ],
    }
    messages = adapter.parse_webhook(payload, tenant_id="dinamomotos")
    assert messages == []


def test_parse_webhook_returns_empty_on_invalid_payload(adapter):
    """Garbage payload — no `object` key. Should return [], not raise."""
    messages = adapter.parse_webhook({"garbage": "yes"}, tenant_id="t")
    assert messages == []


def test_parse_webhook_handles_multiple_messages_in_one_change(adapter):
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
                            "messages": [
                                {
                                    "from": "5215555550001",
                                    "id": "wamid.A",
                                    "timestamp": "1",
                                    "text": {"body": "uno"},
                                    "type": "text",
                                },
                                {
                                    "from": "5215555550002",
                                    "id": "wamid.B",
                                    "timestamp": "2",
                                    "text": {"body": "dos"},
                                    "type": "text",
                                },
                            ],
                        },
                    }
                ],
            }
        ],
    }
    messages = adapter.parse_webhook(payload, tenant_id="t")
    assert len(messages) == 2
    assert messages[0].text == "uno"
    assert messages[1].text == "dos"


def test_parse_webhook_handles_non_text_message_without_text_field(adapter):
    """Image/audio/etc messages without media node fall through to text=None."""
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
                            "messages": [
                                {
                                    "from": "5215555550001",
                                    "id": "wamid.IMG",
                                    "timestamp": "1",
                                    "type": "image",
                                }
                            ],
                        },
                    }
                ],
            }
        ],
    }
    messages = adapter.parse_webhook(payload, tenant_id="t")
    assert len(messages) == 1
    assert messages[0].text is None
    assert messages[0].metadata == {}


# Phase 3c.2 — image / document attachments


def test_parse_webhook_image_extracts_attachment(adapter):
    """Image with media node populates metadata.attachments and text."""
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
                            "messages": [
                                {
                                    "from": "5215555550001",
                                    "id": "wamid.IMG",
                                    "timestamp": "1714579200",
                                    "type": "image",
                                    "image": {
                                        "id": "MEDIA_ABC",
                                        "mime_type": "image/jpeg",
                                        "sha256": "abc123",
                                    },
                                }
                            ],
                        },
                    }
                ],
            }
        ],
    }
    messages = adapter.parse_webhook(payload, tenant_id="t")
    assert len(messages) == 1
    msg = messages[0]
    # No caption -> text becomes "" (empty caption fallback) so NLU still runs.
    assert msg.text == ""
    attachments = msg.metadata["attachments"]
    assert len(attachments) == 1
    assert attachments[0]["media_id"] == "MEDIA_ABC"
    assert attachments[0]["mime_type"] == "image/jpeg"
    # url is filled by the webhook handler post-parse via Graph API.
    assert attachments[0]["url"] == ""
    assert attachments[0]["caption"] is None


def test_parse_webhook_image_with_caption_uses_caption_as_text(adapter):
    """When the customer types a caption with their image, that's the NLU text."""
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
                            "messages": [
                                {
                                    "from": "5215555550001",
                                    "id": "wamid.IMG2",
                                    "timestamp": "1",
                                    "type": "image",
                                    "image": {
                                        "id": "MEDIA_DEF",
                                        "mime_type": "image/jpeg",
                                        "caption": "aquí va mi INE",
                                    },
                                }
                            ],
                        },
                    }
                ],
            }
        ],
    }
    messages = adapter.parse_webhook(payload, tenant_id="t")
    assert messages[0].text == "aquí va mi INE"
    assert messages[0].metadata["attachments"][0]["caption"] == "aquí va mi INE"


def test_parse_webhook_document_attachment(adapter):
    """PDF / document type populates the same attachment shape as image."""
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
                            "messages": [
                                {
                                    "from": "5215555550001",
                                    "id": "wamid.DOC",
                                    "timestamp": "1",
                                    "type": "document",
                                    "document": {
                                        "id": "DOC_MEDIA_ID",
                                        "mime_type": "application/pdf",
                                    },
                                }
                            ],
                        },
                    }
                ],
            }
        ],
    }
    messages = adapter.parse_webhook(payload, tenant_id="t")
    attachments = messages[0].metadata["attachments"]
    assert attachments[0]["mime_type"] == "application/pdf"
    assert attachments[0]["media_id"] == "DOC_MEDIA_ID"
