import httpx

from atendia.channels.base import (
    ChannelAdapter,
    DeliveryReceipt,
    InboundMessage,
    OutboundMessage,
)
from atendia.channels.meta_dto import MetaInboundWebhook
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
                    result.append(InboundMessage(
                        tenant_id=tenant_id,
                        from_phone_e164=f"+{m.from_}",
                        channel_message_id=m.id,
                        text=text,
                        received_at=m.timestamp,
                    ))
        return result

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
