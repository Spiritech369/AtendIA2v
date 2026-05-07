"""Tests for MetaCloudAPIAdapter.fetch_media_url (Phase 3c.2)."""
import respx
from httpx import Response

from atendia.channels.meta_cloud_api import MetaCloudAPIAdapter


def _adapter() -> MetaCloudAPIAdapter:
    return MetaCloudAPIAdapter(
        access_token="TOK",
        app_secret="x",
        api_version="v21.0",
        base_url="https://graph.facebook.com",
    )


@respx.mock
async def test_fetch_media_url_returns_url_on_200() -> None:
    respx.get("https://graph.facebook.com/v21.0/MEDIA_X").mock(
        return_value=Response(200, json={
            "url": "https://lookaside.fbsbx.com/...",
            "mime_type": "image/jpeg",
        }),
    )
    url = await _adapter().fetch_media_url("MEDIA_X")
    assert url == "https://lookaside.fbsbx.com/..."


@respx.mock
async def test_fetch_media_url_returns_empty_on_404() -> None:
    """Media expired or wrong id → graceful empty, not raise."""
    respx.get("https://graph.facebook.com/v21.0/MEDIA_404").mock(
        return_value=Response(404, json={"error": "not found"}),
    )
    url = await _adapter().fetch_media_url("MEDIA_404")
    assert url == ""


@respx.mock
async def test_fetch_media_url_returns_empty_on_transport_error() -> None:
    """Network blip → graceful empty so the webhook never 500s."""
    import httpx
    respx.get("https://graph.facebook.com/v21.0/MEDIA_NET").mock(
        side_effect=httpx.ConnectError("kaboom"),
    )
    url = await _adapter().fetch_media_url("MEDIA_NET")
    assert url == ""


@respx.mock
async def test_fetch_media_url_returns_empty_on_malformed_body() -> None:
    """200 but the JSON body is missing the `url` key."""
    respx.get("https://graph.facebook.com/v21.0/MEDIA_BAD").mock(
        return_value=Response(200, json={"something": "else"}),
    )
    url = await _adapter().fetch_media_url("MEDIA_BAD")
    assert url == ""
