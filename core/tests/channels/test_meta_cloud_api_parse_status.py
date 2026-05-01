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


def test_parse_status_callback_extracts_receipts(adapter):
    payload = {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "WABA_ID",
            "changes": [{
                "field": "messages",
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {"display_phone_number": "x", "phone_number_id": "y"},
                    "statuses": [
                        {"id": "wamid.X", "status": "delivered", "timestamp": "1", "recipient_id": "5215"},
                        {"id": "wamid.Y", "status": "read", "timestamp": "2", "recipient_id": "5215"},
                    ],
                },
            }],
        }],
    }
    receipts = adapter.parse_status_callback(payload)
    assert len(receipts) == 2
    assert receipts[0].channel_message_id == "wamid.X"
    assert receipts[0].status == "delivered"
    assert receipts[1].channel_message_id == "wamid.Y"
    assert receipts[1].status == "read"


def test_parse_status_callback_empty_for_message_only_payload(adapter):
    payload = {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "WABA_ID",
            "changes": [{
                "field": "messages",
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {"display_phone_number": "x", "phone_number_id": "y"},
                    "messages": [{"from": "5215", "id": "wamid.A", "timestamp": "1", "text": {"body": "x"}, "type": "text"}],
                },
            }],
        }],
    }
    receipts = adapter.parse_status_callback(payload)
    assert receipts == []


def test_parse_status_callback_empty_on_invalid_payload(adapter):
    receipts = adapter.parse_status_callback({"garbage": True})
    assert receipts == []
