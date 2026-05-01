import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status
from redis.asyncio import Redis

from atendia.config import get_settings
from atendia.realtime.auth import decode_token
from atendia.realtime.publisher import channel_for

router = APIRouter()


@router.websocket("/ws/conversations/{conversation_id}")
async def conversation_ws(websocket: WebSocket, conversation_id: str) -> None:
    """Subscribe a client to a single conversation's realtime event stream.

    Auth: `?token=<JWT>` query param. The JWT's tenant_id scopes the channel.
    """
    token = websocket.query_params.get("token", "")
    try:
        tenant_id = decode_token(token)
    except Exception:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await websocket.accept()

    redis = Redis.from_url(get_settings().redis_url)
    pubsub = redis.pubsub()
    channel = channel_for(tenant_id=tenant_id, conversation_id=conversation_id)
    await pubsub.subscribe(channel)
    try:
        while True:
            msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if msg is not None and msg.get("type") == "message":
                data = msg["data"]
                if isinstance(data, bytes):
                    data = data.decode("utf-8")
                await websocket.send_text(data)
            await asyncio.sleep(0)
    except WebSocketDisconnect:
        pass
    finally:
        try:
            await pubsub.unsubscribe(channel)
        except Exception:
            pass
        await pubsub.aclose()
        await redis.aclose()
