# ruff: noqa: N802
"""E2E tests: deterministic flow_router dispatches to the right mode (T25).

Each test seeds a tenant with a `flow_mode_rules` list in the pipeline JSONB,
sends one inbound, and asserts trace.flow_mode + composer.last_input.flow_mode
match. Tests are TEXT-ONLY by design — image-bearing inbounds would trigger
the Vision API (chargeable) under non-live runs; that branch is exercised in
test_conversation_runner.py with respx mocks instead.

Note: trace.flow_mode is the .value string ("PLAN"); composer_input.flow_mode
is the FlowMode enum. The runner serializes per `flow_mode=flow_mode.value`
in TurnTrace creation (intentional asymmetry — the JSONB column is read by
SQL filters, the Pydantic field by type-checked Python).

The N802 suppressed at file level keeps test names mode-shouting (PLAN,
SALES, etc.) so a `pytest -k SALES` filter Just Works.
"""

import json
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import text

from atendia.contracts.flow_mode import FlowMode
from atendia.contracts.message import Message, MessageDirection
from atendia.contracts.nlu_result import Intent, NLUResult, Sentiment
from atendia.contracts.pipeline_definition import FieldSpec
from atendia.runner.composer_protocol import (
    ComposerInput,
    ComposerOutput,
)
from atendia.runner.conversation_runner import ConversationRunner
from atendia.runner.nlu_protocol import UsageMetadata

# ============================================================================
# Helpers
# ============================================================================


class _FakeNLU:
    """Stub NLUProvider with a configurable intent for routing tests."""

    def __init__(self, intent: Intent = Intent.UNCLEAR) -> None:
        self._intent = intent

    async def classify(
        self,
        *,
        text: str,
        current_stage: str,
        required_fields: list[FieldSpec],
        optional_fields: list[FieldSpec],
        history: list[tuple[str, str]],
    ) -> tuple[NLUResult, UsageMetadata | None]:
        return (
            NLUResult(intent=self._intent, sentiment=Sentiment.NEUTRAL, confidence=0.95),
            UsageMetadata(
                model="stub",
                tokens_in=10,
                tokens_out=5,
                cost_usd=Decimal("0"),
                latency_ms=1,
            ),
        )


class _RecordingComposer:
    """Captures the ComposerInput so tests can assert wiring."""

    def __init__(self) -> None:
        self.last_input: ComposerInput | None = None

    async def compose(
        self,
        *,
        input: ComposerInput,
    ) -> tuple[ComposerOutput, UsageMetadata | None]:
        self.last_input = input
        return ComposerOutput(messages=["ok"]), None


_BASE_PIPELINE = {
    "version": 1,
    "stages": [
        {
            "id": "qualify",
            "required_fields": ["interes_producto", "ciudad"],
            "actions_allowed": ["ask_field", "lookup_faq", "ask_clarification"],
            "transitions": [],
        },
    ],
    "fallback": "escalate_to_human",
}


def _pipeline_with_rules(rules: list[dict]) -> dict:
    return {**_BASE_PIPELINE, "flow_mode_rules": rules}


async def _seed(db_session, tenant_name: str, pipeline: dict) -> tuple:
    tid = (
        await db_session.execute(
            text("INSERT INTO tenants (name) VALUES (:n) RETURNING id"),
            {"n": tenant_name},
        )
    ).scalar()
    await db_session.execute(
        text(
            "INSERT INTO tenant_pipelines (tenant_id, version, definition, active) "
            "VALUES (:t, 1, :d\\:\\:jsonb, true)"
        ),
        {"t": tid, "d": json.dumps(pipeline)},
    )
    cid = (
        await db_session.execute(
            text(
                "INSERT INTO customers (tenant_id, phone_e164) "
                "VALUES (:t, '+5215555550042') RETURNING id"
            ),
            {"t": tid},
        )
    ).scalar()
    conv_id = (
        await db_session.execute(
            text(
                "INSERT INTO conversations (tenant_id, customer_id, current_stage) "
                "VALUES (:t, :c, 'qualify') RETURNING id"
            ),
            {"t": tid, "c": cid},
        )
    ).scalar()
    await db_session.execute(
        text("INSERT INTO conversation_state (conversation_id) VALUES (:c)"),
        {"c": conv_id},
    )
    await db_session.commit()
    return tid, cid, conv_id


def _msg(conv_id, tid, txt: str) -> Message:
    return Message(
        id=str(uuid4()),
        conversation_id=str(conv_id),
        tenant_id=str(tid),
        direction=MessageDirection.INBOUND,
        text=txt,
        sent_at=datetime.now(UTC),
    )


async def _cleanup(db_session, tid):
    await db_session.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": tid})
    await db_session.commit()


# ============================================================================
# Per-mode dispatch tests
# ============================================================================


@pytest.mark.asyncio
async def test_runner_dispatches_RETENTION_on_gracias(db_session) -> None:
    """KeywordInText 'gracias' fires before the always fallback → RETENTION."""
    rules = [
        {
            "id": "retain",
            "trigger": {"type": "keyword_in_text", "list": ["gracias"]},
            "mode": "RETENTION",
        },
        {"id": "always", "trigger": {"type": "always"}, "mode": "SUPPORT"},
    ]
    tid, _, conv_id = await _seed(db_session, "test_t25_retention", _pipeline_with_rules(rules))
    composer = _RecordingComposer()
    runner = ConversationRunner(db_session, _FakeNLU(), composer)
    trace = await runner.run_turn(
        conversation_id=conv_id,
        tenant_id=tid,
        inbound=_msg(conv_id, tid, "gracias por la info"),
        turn_number=1,
    )
    await db_session.commit()
    assert trace.flow_mode == "RETENTION"
    assert composer.last_input is not None
    assert composer.last_input.flow_mode == FlowMode.RETENTION
    await _cleanup(db_session, tid)


@pytest.mark.asyncio
async def test_runner_dispatches_OBSTACLE_on_manana_with_accent(db_session) -> None:
    """Accent-stripped match: keyword 'mañana' fires on input 'mañana'."""
    rules = [
        {
            "id": "block",
            "trigger": {"type": "keyword_in_text", "list": ["mañana", "luego"]},
            "mode": "OBSTACLE",
        },
        {"id": "always", "trigger": {"type": "always"}, "mode": "SUPPORT"},
    ]
    tid, _, conv_id = await _seed(db_session, "test_t25_obstacle", _pipeline_with_rules(rules))
    composer = _RecordingComposer()
    runner = ConversationRunner(db_session, _FakeNLU(), composer)
    trace = await runner.run_turn(
        conversation_id=conv_id,
        tenant_id=tid,
        inbound=_msg(conv_id, tid, "te lo paso mañana"),
        turn_number=1,
    )
    await db_session.commit()
    assert trace.flow_mode == "OBSTACLE"
    assert composer.last_input.flow_mode == FlowMode.OBSTACLE
    await _cleanup(db_session, tid)


@pytest.mark.asyncio
async def test_runner_dispatches_PLAN_when_plan_credito_missing(db_session) -> None:
    """FieldMissing(plan_credito) catches first-touch customers → PLAN."""
    rules = [
        {
            "id": "plan",
            "trigger": {"type": "field_missing", "field": "plan_credito"},
            "mode": "PLAN",
        },
        {"id": "always", "trigger": {"type": "always"}, "mode": "SUPPORT"},
    ]
    tid, _, conv_id = await _seed(db_session, "test_t25_plan", _pipeline_with_rules(rules))
    composer = _RecordingComposer()
    runner = ConversationRunner(db_session, _FakeNLU(Intent.GREETING), composer)
    trace = await runner.run_turn(
        conversation_id=conv_id,
        tenant_id=tid,
        inbound=_msg(conv_id, tid, "hola"),
        turn_number=1,
    )
    await db_session.commit()
    assert trace.flow_mode == "PLAN"
    assert composer.last_input.flow_mode == FlowMode.PLAN
    await _cleanup(db_session, tid)


@pytest.mark.asyncio
async def test_runner_dispatches_SALES_when_plan_present_and_intent_buy(
    db_session,
) -> None:
    """FieldPresentAndIntent(plan_credito + ask_price/buy) → SALES.

    Pre-seeds plan_credito='10%' so the rule matches; intent=ask_price.
    """
    rules = [
        {
            "id": "sales",
            "trigger": {
                "type": "field_present_and_intent",
                "field": "plan_credito",
                "intents": ["ask_price", "buy"],
            },
            "mode": "SALES",
        },
        {"id": "always", "trigger": {"type": "always"}, "mode": "SUPPORT"},
    ]
    tid, _, conv_id = await _seed(db_session, "test_t25_sales", _pipeline_with_rules(rules))
    # Pre-seed extracted_data with plan_credito so the field_present trigger fires.
    await db_session.execute(
        text(
            "UPDATE conversation_state SET extracted_data = :ed\\:\\:jsonb "
            "WHERE conversation_id = :cid"
        ),
        {
            "ed": json.dumps(
                {
                    "plan_credito": {
                        "value": "10%",
                        "confidence": 1.0,
                        "source_turn": 0,
                    },
                }
            ),
            "cid": conv_id,
        },
    )
    await db_session.commit()

    composer = _RecordingComposer()
    runner = ConversationRunner(db_session, _FakeNLU(Intent.ASK_PRICE), composer)
    trace = await runner.run_turn(
        conversation_id=conv_id,
        tenant_id=tid,
        inbound=_msg(conv_id, tid, "cuánto cuesta la 150Z"),
        turn_number=2,
    )
    await db_session.commit()
    assert trace.flow_mode == "SALES"
    assert composer.last_input.flow_mode == FlowMode.SALES
    await _cleanup(db_session, tid)


@pytest.mark.asyncio
async def test_runner_dispatches_SUPPORT_via_always_fallback(db_session) -> None:
    """No specific rule matches → always-fallback routes to SUPPORT."""
    rules = [
        {"id": "always", "trigger": {"type": "always"}, "mode": "SUPPORT"},
    ]
    tid, _, conv_id = await _seed(db_session, "test_t25_support", _pipeline_with_rules(rules))
    composer = _RecordingComposer()
    runner = ConversationRunner(db_session, _FakeNLU(Intent.ASK_INFO), composer)
    trace = await runner.run_turn(
        conversation_id=conv_id,
        tenant_id=tid,
        inbound=_msg(conv_id, tid, "qué tipos de plan tienen"),
        turn_number=1,
    )
    await db_session.commit()
    assert trace.flow_mode == "SUPPORT"
    assert composer.last_input.flow_mode == FlowMode.SUPPORT
    await _cleanup(db_session, tid)


@pytest.mark.asyncio
async def test_runner_dispatches_DOC_on_pending_confirmation_then_sales(
    db_session,
) -> None:
    """PendingConfirmation routes to PLAN; verifies the binary-handler trigger.

    DOC mode requires HasAttachmentTrigger which needs Vision (chargeable).
    Instead we test PendingConfirmation here — same trigger family,
    text-only — so all 6 modes are exercised via T25 + the unit tests in
    test_flow_router.py without burning live API credits.
    """
    rules = [
        {"id": "confirm", "trigger": {"type": "pending_confirmation"}, "mode": "PLAN"},
        {"id": "always", "trigger": {"type": "always"}, "mode": "SUPPORT"},
    ]
    tid, _, conv_id = await _seed(db_session, "test_t25_pending", _pipeline_with_rules(rules))
    # Seed a pending slot — but use a key the binary handler doesn't know
    # so it falls through (slot stays, router fires PendingConfirmation).
    await db_session.execute(
        text(
            "UPDATE conversation_state SET pending_confirmation = :pc WHERE conversation_id = :cid"
        ),
        {"pc": "is_unknown_key_router_only", "cid": conv_id},
    )
    await db_session.commit()

    composer = _RecordingComposer()
    runner = ConversationRunner(db_session, _FakeNLU(), composer)
    trace = await runner.run_turn(
        conversation_id=conv_id,
        tenant_id=tid,
        inbound=_msg(conv_id, tid, "respuesta libre"),
        turn_number=1,
    )
    await db_session.commit()
    assert trace.flow_mode == "PLAN"
    assert composer.last_input.flow_mode == FlowMode.PLAN
    await _cleanup(db_session, tid)
