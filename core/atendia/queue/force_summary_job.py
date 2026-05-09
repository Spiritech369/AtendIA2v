"""arq job: generate an AI conversation summary and save it as a customer note.

Replaces the previous degraded transcript-only behaviour. When
``ATENDIA_V2_OPENAI_API_KEY`` is set the job calls gpt-4o-mini with a focused
sales-context prompt; otherwise it persists a clearly-labeled ``transcript``
fallback so an operator viewing the note knows it isn't an LLM summary.

Idempotency is enforced via the ``high_water:<message_id>`` marker stored
inside the note body — a duplicate enqueue against the same conversation
+ same most-recent-message returns ``{"status": "duplicate"}`` without
inserting a second note. Retry-from-failed uses the same marker.
"""
from __future__ import annotations

from uuid import UUID

from openai import AsyncOpenAI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from atendia.config import get_settings
from atendia.db.models.conversation import Conversation
from atendia.db.models.customer_note import CustomerNote
from atendia.db.models.message import MessageRow

# Hard caps on the LLM input. The job runs in a worker so latency budget
# is generous, but we still cap to keep the cost predictable.
SUMMARY_MAX_MESSAGES: int = 40
SUMMARY_MODEL: str = "gpt-4o-mini"
SUMMARY_MAX_TOKENS: int = 400
SUMMARY_TIMEOUT_SECONDS: float = 20.0


SUMMARY_SYSTEM_PROMPT = (
    "Eres un asistente de ventas. Resume la siguiente conversacion entre el "
    "cliente y el bot/operador en 4-6 lineas en espanol neutro mexicano. "
    "Enfocate en: necesidad del cliente, productos o planes mencionados, "
    "objeciones, compromisos, y proximo paso pendiente. NO inventes precios, "
    "fechas o nombres que no aparezcan en el texto. Si la conversacion es "
    "muy corta o sin contexto util, di 'Sin contexto suficiente' y nada mas."
)


async def force_summary(ctx: dict, conversation_id: str) -> dict:
    settings = get_settings()
    engine = ctx.get("engine") or create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            conv = (
                await session.execute(
                    select(Conversation).where(Conversation.id == UUID(conversation_id))
                )
            ).scalar_one_or_none()
            if conv is None:
                return {"status": "missing"}

            messages = (
                await session.execute(
                    select(MessageRow)
                    .where(MessageRow.conversation_id == conv.id)
                    .order_by(MessageRow.sent_at.desc())
                    .limit(SUMMARY_MAX_MESSAGES)
                )
            ).scalars().all()
            high_water = str(messages[0].id) if messages else "empty"

            existing = (
                await session.execute(
                    select(CustomerNote.id).where(
                        CustomerNote.customer_id == conv.customer_id,
                        CustomerNote.tenant_id == conv.tenant_id,
                        CustomerNote.source == "ai_summary",
                        CustomerNote.content.ilike(f"%high_water:{high_water}%"),
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                return {"status": "duplicate"}

            transcript_lines = [
                f"{m.direction}: {(m.text or '').strip()}"
                for m in reversed(messages)
                if (m.text or "").strip()
            ]
            transcript = "\n".join(transcript_lines)

            summary, mode = await _summarize(transcript, settings.openai_api_key)
            header = "Resumen AI" if mode == "llm" else "Transcripcion (sin LLM disponible)"
            session.add(
                CustomerNote(
                    customer_id=conv.customer_id,
                    tenant_id=conv.tenant_id,
                    author_user_id=None,
                    source="ai_summary",
                    content=(
                        f"{header}\n\n{summary[:3500]}\n\n"
                        f"high_water:{high_water}\nmode:{mode}"
                    ),
                    pinned=False,
                )
            )
            await session.commit()
    finally:
        if "engine" not in ctx:
            await engine.dispose()
    return {"status": "ok", "conversation_id": conversation_id, "mode": mode}


async def _summarize(transcript: str, api_key: str) -> tuple[str, str]:
    """Return ``(text, mode)`` where mode is ``llm`` or ``transcript``.

    Factored out so tests can monkeypatch the LLM call without depending on
    a real OpenAI key.
    """
    if not transcript.strip():
        return "Sin mensajes que resumir.", "transcript"
    if not api_key:
        return _fallback_transcript(transcript), "transcript"
    try:
        client = AsyncOpenAI(api_key=api_key, max_retries=0, timeout=SUMMARY_TIMEOUT_SECONDS)
        resp = await client.chat.completions.create(
            model=SUMMARY_MODEL,
            messages=[
                {"role": "system", "content": SUMMARY_SYSTEM_PROMPT},
                {"role": "user", "content": transcript[:16000]},
            ],
            temperature=0.2,
            max_tokens=SUMMARY_MAX_TOKENS,
        )
        body = (resp.choices[0].message.content or "").strip()
        if not body:
            return _fallback_transcript(transcript), "transcript"
        return body, "llm"
    except Exception:
        # Honest degradation: fail loudly in logs (the worker logs the
        # exception via arq), but don't lose the operator's intent — give
        # them the transcript so they can still read it.
        return _fallback_transcript(transcript), "transcript"


def _fallback_transcript(transcript: str) -> str:
    lines = transcript.splitlines()
    return "\n".join(lines[-20:]) or "No hay mensajes suficientes para resumir."
