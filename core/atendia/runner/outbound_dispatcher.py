"""Maps orchestrator action → outbound text for Phase 2 (no LLM Composer yet).

Phase 3 replaces this with the real Composer (gpt-4o). The interface is:
- `text_for_action(action)` returns the message text, or None to skip.
- `dispatch(decision, ...)` enqueues an OutboundMessage if the action produces text.
"""
from uuid import UUID, uuid4

from arq.connections import ArqRedis

from atendia.channels.base import OutboundMessage
from atendia.queue.enqueue import enqueue_outbound


# Actions that produce an outbound text in Phase 2.
OUTBOUND_ACTIONS: set[str] = {
    "greet",
    "ask_field",
    "lookup_faq",
    "ask_clarification",
    "quote",
    "explain_payment_options",
    "close",
}

# Actions that DON'T produce an outbound text (handled by other paths).
SKIP_ACTIONS: set[str] = {
    "escalate_to_human",  # creates a human_handoffs row; agent picks up
    "schedule_followup",  # creates a followups_scheduled row; worker sends later
    "book_appointment",   # creates a booking; confirmation goes via different flow
    "search_catalog",     # reading the catalog; data goes into next turn's context
}


_PHASE2_TEXTS: dict[str, str] = {
    "greet": "¡Hola! Soy tu asistente. ¿En qué te puedo ayudar?",
    "ask_field": "Me podrías compartir más detalles?",
    "lookup_faq": "Déjame revisar nuestra información para responderte.",
    "ask_clarification": "Disculpa, no te entendí del todo. ¿Podrías reformular?",
    "quote": "El precio depende del modelo y opciones. ¿Cuál te interesa? Te paso el costo exacto.",
    "explain_payment_options": "Aceptamos efectivo, transferencia y crédito. ¿Cuál te conviene?",
    "close": "¡Perfecto! Te paso el siguiente paso para cerrar.",
}


def text_for_action(action: str) -> str | None:
    """Return the outbound text for an action, or None if the action shouldn't send one."""
    return _PHASE2_TEXTS.get(action)


async def dispatch(
    arq_redis: ArqRedis,
    *,
    action: str,
    tenant_id: UUID,
    to_phone_e164: str,
    conversation_id: UUID,
) -> str | None:
    """Enqueue an outbound message based on the orchestrator's action.

    Returns the enqueued job_id on success, None if the action was skipped or unknown.
    """
    text = text_for_action(action)
    if text is None:
        return None

    msg = OutboundMessage(
        tenant_id=str(tenant_id),
        to_phone_e164=to_phone_e164,
        text=text,
        idempotency_key=f"out:{conversation_id}:{uuid4().hex[:12]}",
        metadata={"action": action},
    )
    return await enqueue_outbound(arq_redis, msg)
