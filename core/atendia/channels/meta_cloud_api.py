import httpx

from atendia.channels.base import (
    ChannelAdapter,
    DeliveryReceipt,
    InboundAttachment,
    InboundMessage,
    InboundMessageMetadata,
    OutboundMessage,
)
from atendia.channels.meta_dto import MetaInboundMessage, MetaInboundWebhook
from atendia.channels.meta_signing import verify_meta_signature


class MetaCloudAPIAdapter(ChannelAdapter):
    name = "meta_cloud_api"

    def __init__(
        self,
        *,
        access_token: str,
        app_secret: str,
        api_version: str = "v21.0",
        base_url: str = "https://graph.facebook.com",
        timeout_seconds: float = 10.0,
    ) -> None:
        self._access_token = access_token
        self._app_secret = app_secret
        self._api_version = api_version
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds

    async def send(
        self,
        msg: OutboundMessage,
        *,
        phone_number_id: str,
        message_id: str,
    ) -> DeliveryReceipt:
        url = f"{self._base_url}/{self._api_version}/{phone_number_id}/messages"
        headers = {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json",
        }
        if msg.text is not None:
            body: dict = {
                "messaging_product": "whatsapp",
                "to": msg.to_phone_e164.lstrip("+"),
                "type": "text",
                "text": {"body": msg.text},
            }
        elif msg.template is not None:
            body = {
                "messaging_product": "whatsapp",
                "to": msg.to_phone_e164.lstrip("+"),
                "type": "template",
                "template": msg.template,
            }
        else:  # pragma: no cover  -- model_validator prevents this
            raise ValueError("OutboundMessage has neither text nor template")

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            try:
                resp = await client.post(url, headers=headers, json=body)
            except httpx.HTTPError as e:
                return DeliveryReceipt(
                    message_id=message_id,
                    channel_message_id=None,
                    status="failed",
                    error=f"transport_error: {type(e).__name__}: {e}",
                )

        if resp.status_code >= 400:
            try:
                err = resp.json().get("error", {})
            except Exception:  # pragma: no cover
                err = {}
            return DeliveryReceipt(
                message_id=message_id,
                channel_message_id=None,
                status="failed",
                error=f"meta_error_{err.get('code', resp.status_code)}: {err.get('message', resp.text)}",
            )

        try:
            data = resp.json()
        except Exception:  # pragma: no cover
            data = {}
        wamid = (data.get("messages") or [{}])[0].get("id") if isinstance(data, dict) else None
        if not wamid:
            return DeliveryReceipt(
                message_id=message_id,
                channel_message_id=None,
                status="failed",
                error="no_message_id_in_response",
            )
        return DeliveryReceipt(
            message_id=message_id,
            channel_message_id=wamid,
            status="sent",
            error=None,
        )

    def validate_signature(self, body: bytes, signature_header: str) -> bool:
        return verify_meta_signature(body, signature_header, self._app_secret)

    def parse_webhook(self, payload: dict, tenant_id: str) -> list[InboundMessage]:
        try:
            wh = MetaInboundWebhook.model_validate(payload)
        except Exception:
            return []
        result: list[InboundMessage] = []
        for entry in wh.entry:
            for change in entry.changes:
                msgs = change.value.messages or []
                for m in msgs:
                    text = m.text.body if m.text else None
                    attachments = _attachments_from_message(m)
                    if attachments:
                        # Image/document/etc. — caption (if any) becomes the
                        # text payload so downstream NLU has something to read.
                        text = attachments[0].caption or ""
                    metadata: dict = {}
                    if attachments:
                        metadata = InboundMessageMetadata(
                            attachments=attachments,
                        ).model_dump(mode="json")
                    result.append(InboundMessage(
                        tenant_id=tenant_id,
                        from_phone_e164=f"+{m.from_}",
                        channel_message_id=m.id,
                        text=text,
                        received_at=m.timestamp,
                        metadata=metadata,
                    ))
        return result

    async def fetch_media_url(
        self,
        media_id: str,
        *,
        timeout_seconds: float = 3.0,
    ) -> str:
        """Resolve a Meta media_id to its lookaside download URL.

        Returns "" on any failure (network, 4xx, malformed body) — the
        webhook handler logs and persists the empty URL so Vision is skipped
        for that turn rather than crashing the request. The lookaside URL
        has a ~1h TTL; callers should download / send to Vision promptly.
        """
        url = f"{self._base_url}/{self._api_version}/{media_id}"
        headers = {"Authorization": f"Bearer {self._access_token}"}
        try:
            async with httpx.AsyncClient(timeout=timeout_seconds) as client:
                resp = await client.get(url, headers=headers)
        except httpx.HTTPError:
            return ""
        if resp.status_code >= 400:
            return ""
        try:
            return str(resp.json().get("url", "")) or ""
        except Exception:
            return ""

    def parse_status_callback(self, payload: dict) -> list[DeliveryReceipt]:
        try:
            wh = MetaInboundWebhook.model_validate(payload)
        except Exception:
            return []
        result: list[DeliveryReceipt] = []
        for entry in wh.entry:
            for change in entry.changes:
                statuses = change.value.statuses or []
                for s in statuses:
                    result.append(DeliveryReceipt(
                        message_id="",  # filled by webhook receiver from messages table lookup
                        channel_message_id=s.id,
                        status=s.status,  # type: ignore[arg-type]
                        error=None,
                    ))
        return result


def _attachments_from_message(m: MetaInboundMessage) -> list[InboundAttachment]:
    """Pull image/document/audio/video media nodes off a Meta message.

    A single inbound message carries at most one media node (Meta sends
    a separate webhook per attachment). The list shape matches the
    canonical Attachment contract for forward compatibility.
    """
    for node in (m.image, m.document, m.audio, m.video):
        if node is None:
            continue
        return [InboundAttachment(
            media_id=node.id,
            mime_type=node.mime_type,
            url="",  # filled in by the webhook handler via fetch_media_url
            caption=node.caption,
        )]
    return []
