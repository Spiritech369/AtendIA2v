"""Enqueue outbound messages onto the arq queue.

Phase 3b: dispatcher no longer holds canned text. The Composer (canned or
OpenAI) produces the messages; the dispatcher just enqueues them.
"""
from uuid import UUID, uuid4

from arq.connections import ArqRedis

from atendia.channels.base import OutboundMessage
from atendia.queue.enqueue import enqueue_outbound

COMPOSED_ACTIONS: set[str] = {
    "greet", "ask_field", "lookup_faq", "ask_clarification",
    "quote", "explain_payment_options", "close",
}

SKIP_ACTIONS: set[str] = {
    "escalate_to_human", "schedule_followup", "book_appointment", "search_catalog",
}


async def enqueue_messages(
    arq_redis: ArqRedis,
    *,
    messages: list[str],
    tenant_id: UUID,
    to_phone_e164: str,
    conversation_id: UUID,
    turn_number: int,
    action: str,
) -> list[str]:
    """Enqueue N OutboundMessage jobs (one per message)."""
    job_ids: list[str] = []
    for i, text in enumerate(messages):
        msg = OutboundMessage(
            tenant_id=str(tenant_id),
            to_phone_e164=to_phone_e164,
            text=text,
            idempotency_key=f"out:{conversation_id}:{turn_number}:{i}:{uuid4().hex[:6]}",
            metadata={"action": action, "message_index": i, "of": len(messages)},
        )
        job_ids.append(await enqueue_outbound(arq_redis, msg))
    return job_ids
