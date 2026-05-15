"""Tests for the ``force_summary`` arq job.

Two paths to cover:

- ``llm`` mode: when ``OPENAI_API_KEY`` is set, ``_summarize`` calls
  gpt-4o-mini and persists ``mode:llm`` in the note body.
- ``transcript`` fallback: when the key is missing or the call fails, the
  note body is the recent transcript with ``mode:transcript``.

The OpenAI client is monkeypatched so the test never makes a real network
call. The DB and the rest of the worker codepath run for real.
"""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from atendia.config import get_settings
from atendia.queue import force_summary_job


@pytest.fixture
def seeded_conversation():
    """Insert tenant + customer + conversation + a few messages, return ids."""

    async def _seed() -> dict[str, str]:
        engine = create_async_engine(get_settings().database_url)
        try:
            async with engine.begin() as conn:
                tid = (
                    await conn.execute(
                        text("INSERT INTO tenants (name) VALUES (:n) RETURNING id"),
                        {"n": f"fs_{uuid4().hex[:10]}"},
                    )
                ).scalar()
                cid = (
                    await conn.execute(
                        text(
                            "INSERT INTO customers (tenant_id, phone_e164, name) "
                            "VALUES (:t, :p, 'Pruebas') RETURNING id"
                        ),
                        {"t": tid, "p": f"+5215{uuid4().hex[:9]}"},
                    )
                ).scalar()
                conv = (
                    await conn.execute(
                        text(
                            "INSERT INTO conversations (tenant_id, customer_id) "
                            "VALUES (:t, :c) RETURNING id"
                        ),
                        {"t": tid, "c": cid},
                    )
                ).scalar()
                await conn.execute(
                    text("INSERT INTO conversation_state (conversation_id) VALUES (:c)"),
                    {"c": conv},
                )
                for i, (direction, body) in enumerate(
                    [
                        ("inbound", "Hola, quiero info"),
                        ("outbound", "Claro, dime que plan"),
                        ("inbound", "El de 36 meses"),
                    ]
                ):
                    await conn.execute(
                        text(
                            "INSERT INTO messages "
                            "(conversation_id, tenant_id, direction, text, sent_at) "
                            "VALUES (:c, :t, :d, :b, now() + make_interval(secs => :i))"
                        ),
                        {"c": conv, "t": tid, "d": direction, "b": body, "i": i},
                    )
            return {"tenant_id": str(tid), "customer_id": str(cid), "conversation_id": str(conv)}
        finally:
            await engine.dispose()

    seeded = asyncio.run(_seed())
    yield seeded

    async def _cleanup() -> None:
        engine = create_async_engine(get_settings().database_url)
        try:
            async with engine.begin() as conn:
                await conn.execute(
                    text("DELETE FROM tenants WHERE id = :t"),
                    {"t": seeded["tenant_id"]},
                )
        finally:
            await engine.dispose()

    asyncio.run(_cleanup())


async def _read_summary_note(customer_id: str) -> dict[str, Any] | None:
    engine = create_async_engine(get_settings().database_url)
    try:
        async with engine.connect() as conn:
            row = (
                await conn.execute(
                    text(
                        "SELECT content, source FROM customer_notes "
                        "WHERE customer_id = :c AND source = 'ai_summary' "
                        "ORDER BY created_at DESC LIMIT 1"
                    ),
                    {"c": customer_id},
                )
            ).one_or_none()
            if row is None:
                return None
            return {"content": row.content, "source": row.source}
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_force_summary_falls_back_to_transcript_without_key(
    seeded_conversation, monkeypatch
) -> None:
    fake_settings = type(
        "S",
        (),
        {"database_url": get_settings().database_url, "openai_api_key": ""},
    )()
    monkeypatch.setattr(
        "atendia.queue.force_summary_job.get_settings",
        lambda: fake_settings,
    )
    result = await force_summary_job.force_summary({}, seeded_conversation["conversation_id"])
    assert result["status"] == "ok"
    assert result["mode"] == "transcript"
    note = await _read_summary_note(seeded_conversation["customer_id"])
    assert note is not None
    assert "Transcripcion (sin LLM disponible)" in note["content"]
    assert "mode:transcript" in note["content"]
    assert "Hola, quiero info" in note["content"]


@pytest.mark.asyncio
async def test_force_summary_uses_llm_when_summarize_returns_llm(
    seeded_conversation, monkeypatch
) -> None:
    """We monkeypatch ``_summarize`` to simulate a successful LLM call so
    the test never depends on a real OpenAI key."""

    async def fake_summarize(transcript: str, api_key: str) -> tuple[str, str]:
        assert "Hola, quiero info" in transcript
        return "El cliente pregunto por el plan a 36 meses; pendiente cotizacion.", "llm"

    monkeypatch.setattr(force_summary_job, "_summarize", fake_summarize)

    result = await force_summary_job.force_summary({}, seeded_conversation["conversation_id"])
    assert result["status"] == "ok"
    assert result["mode"] == "llm"
    note = await _read_summary_note(seeded_conversation["customer_id"])
    assert note is not None
    assert "Resumen AI" in note["content"]
    assert "mode:llm" in note["content"]
    assert "El cliente pregunto" in note["content"]


@pytest.mark.asyncio
async def test_force_summary_idempotent_on_same_high_water(
    seeded_conversation, monkeypatch
) -> None:
    async def fake_summarize(transcript: str, api_key: str) -> tuple[str, str]:
        return "X", "llm"

    monkeypatch.setattr(force_summary_job, "_summarize", fake_summarize)

    first = await force_summary_job.force_summary({}, seeded_conversation["conversation_id"])
    second = await force_summary_job.force_summary({}, seeded_conversation["conversation_id"])
    assert first["status"] == "ok"
    assert second["status"] == "duplicate"
