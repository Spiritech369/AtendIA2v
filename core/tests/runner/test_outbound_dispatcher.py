"""Tests for outbound_dispatcher.enqueue_messages.

Phase 3b: dispatcher no longer holds canned text. The Composer (canned or
OpenAI) produces the messages; the dispatcher just enqueues them.
"""
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from atendia.runner.outbound_dispatcher import (
    COMPOSED_ACTIONS, SKIP_ACTIONS, enqueue_messages,
)


@pytest.fixture
def fake_arq():
    return AsyncMock()


@pytest.fixture(autouse=True)
def patch_enqueue_outbound(monkeypatch):
    calls = []

    async def fake_enqueue(arq_redis, msg):
        calls.append(msg)
        return f"job-{len(calls)}"

    monkeypatch.setattr(
        "atendia.runner.outbound_dispatcher.enqueue_outbound", fake_enqueue,
    )
    return calls


async def test_enqueue_messages_one_message(fake_arq, patch_enqueue_outbound):
    job_ids = await enqueue_messages(
        fake_arq,
        messages=["¡Hola!"],
        tenant_id=uuid4(), to_phone_e164="+5215551234567",
        conversation_id=uuid4(), turn_number=1, action="greet",
    )
    assert len(job_ids) == 1
    assert len(patch_enqueue_outbound) == 1
    assert patch_enqueue_outbound[0].text == "¡Hola!"


async def test_enqueue_messages_two_messages(fake_arq, patch_enqueue_outbound):
    job_ids = await enqueue_messages(
        fake_arq,
        messages=["¡Hola!", "¿En qué te ayudo?"],
        tenant_id=uuid4(), to_phone_e164="+5215551234567",
        conversation_id=uuid4(), turn_number=1, action="greet",
    )
    assert len(job_ids) == 2
    assert len(patch_enqueue_outbound) == 2
    assert patch_enqueue_outbound[0].text == "¡Hola!"
    assert patch_enqueue_outbound[1].text == "¿En qué te ayudo?"


async def test_enqueue_messages_idempotency_keys_unique(fake_arq, patch_enqueue_outbound):
    cid = uuid4()
    await enqueue_messages(
        fake_arq, messages=["a", "b"],
        tenant_id=uuid4(), to_phone_e164="+x",
        conversation_id=cid, turn_number=1, action="greet",
    )
    keys = [m.idempotency_key for m in patch_enqueue_outbound]
    assert keys[0] != keys[1]
    assert "1:0" in keys[0]
    assert "1:1" in keys[1]


async def test_enqueue_messages_metadata_includes_index(fake_arq, patch_enqueue_outbound):
    await enqueue_messages(
        fake_arq, messages=["a", "b"],
        tenant_id=uuid4(), to_phone_e164="+x",
        conversation_id=uuid4(), turn_number=2, action="greet",
    )
    assert patch_enqueue_outbound[0].metadata == {
        "action": "greet", "message_index": 0, "of": 2,
    }
    assert patch_enqueue_outbound[1].metadata == {
        "action": "greet", "message_index": 1, "of": 2,
    }


def test_composed_actions_taxonomy():
    assert "greet" in COMPOSED_ACTIONS
    assert "ask_field" in COMPOSED_ACTIONS
    assert "lookup_faq" in COMPOSED_ACTIONS
    assert "ask_clarification" in COMPOSED_ACTIONS
    assert "quote" in COMPOSED_ACTIONS
    assert "explain_payment_options" in COMPOSED_ACTIONS
    assert "close" in COMPOSED_ACTIONS
    assert "escalate_to_human" in SKIP_ACTIONS
    assert "schedule_followup" in SKIP_ACTIONS
    assert COMPOSED_ACTIONS.isdisjoint(SKIP_ACTIONS)
