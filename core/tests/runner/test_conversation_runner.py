import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text

from atendia.contracts.message import Message, MessageDirection
from atendia.contracts.nlu_result import Intent, NLUResult, Sentiment
from atendia.contracts.pipeline_definition import FieldSpec
from atendia.runner.composer_canned import CannedComposer
from atendia.runner.composer_protocol import (
    ComposerInput,
    ComposerOutput,
)
from atendia.runner.conversation_runner import ConversationRunner
from atendia.runner.nlu_canned import CannedNLU
from atendia.runner.nlu_protocol import UsageMetadata

FIXTURES_DIR = Path(__file__).parent / "fixtures"


PIPELINE_QUALIFY_QUOTE = {
    "version": 1,
    "stages": [
        {
            "id": "qualify",
            "required_fields": ["interes_producto", "ciudad"],
            "actions_allowed": ["ask_field", "lookup_faq", "ask_clarification"],
            "transitions": [
                {"to": "quote", "when": "all_required_fields_present AND intent == ask_price"},
            ],
        },
        {
            "id": "quote",
            "actions_allowed": ["quote", "ask_clarification"],
            "transitions": [],
        },
    ],
    "tone": {"register": "informal_mexicano"},
    "fallback": "escalate_to_human",
}


async def _seed_tenant_with_pipeline(db_session, tenant_name: str) -> tuple:
    tid = (await db_session.execute(
        text("INSERT INTO tenants (name) VALUES (:n) RETURNING id"),
        {"n": tenant_name},
    )).scalar()
    await db_session.execute(
        text("INSERT INTO tenant_pipelines (tenant_id, version, definition, active) "
             "VALUES (:t, 1, :d\\:\\:jsonb, true)"),
        {"t": tid, "d": json.dumps(PIPELINE_QUALIFY_QUOTE)},
    )
    cid = (await db_session.execute(
        text("INSERT INTO customers (tenant_id, phone_e164) VALUES (:t, '+5215555550037') RETURNING id"),
        {"t": tid},
    )).scalar()
    conv_id = (await db_session.execute(
        text("INSERT INTO conversations (tenant_id, customer_id, current_stage) "
             "VALUES (:t, :c, 'qualify') RETURNING id"),
        {"t": tid, "c": cid},
    )).scalar()
    await db_session.execute(
        text("INSERT INTO conversation_state (conversation_id) VALUES (:c)"),
        {"c": conv_id},
    )
    await db_session.commit()
    return tid, cid, conv_id


def _make_inbound(conversation_id, tenant_id, txt: str) -> Message:
    return Message(
        id=str(uuid4()),
        conversation_id=str(conversation_id),
        tenant_id=str(tenant_id),
        direction=MessageDirection.INBOUND,
        text=txt,
        sent_at=datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_runner_extracts_fields_then_transitions_to_quote(db_session):
    tid, cid, conv_id = await _seed_tenant_with_pipeline(db_session, "test_t37_main")

    nlu_provider = CannedNLU(FIXTURES_DIR / "runner_qualify_to_quote.yaml")
    runner = ConversationRunner(db_session, nlu_provider, CannedComposer())

    # Turn 1: client gives info → fields extracted, stays in qualify
    inbound1 = _make_inbound(conv_id, tid, "info de la 150Z, soy de CDMX")
    trace1 = await runner.run_turn(
        conversation_id=conv_id, tenant_id=tid, inbound=inbound1, turn_number=1,
    )
    await db_session.commit()
    assert trace1.state_after["current_stage"] == "qualify"
    assert trace1.state_after["extracted_data"]["interes_producto"]["value"] == "150Z"

    # Turn 2: client asks price → fields complete + intent ask_price → transitions to quote
    inbound2 = _make_inbound(conv_id, tid, "cuánto cuesta?")
    trace2 = await runner.run_turn(
        conversation_id=conv_id, tenant_id=tid, inbound=inbound2, turn_number=2,
    )
    await db_session.commit()
    assert trace2.state_after["current_stage"] == "quote"
    assert trace2.stage_transition == "qualify->quote"

    # Verify events table has stage_exited + stage_entered
    rows = (await db_session.execute(
        text("SELECT type FROM events WHERE conversation_id = :c ORDER BY occurred_at"),
        {"c": conv_id},
    )).fetchall()
    types = [r[0] for r in rows]
    assert "stage_exited" in types
    assert "stage_entered" in types

    # Verify conversation_state row reflects the final stage
    final_stage = (await db_session.execute(
        text("SELECT current_stage FROM conversations WHERE id = :c"),
        {"c": conv_id},
    )).scalar()
    assert final_stage == "quote"

    # Verify turn_traces has 2 rows
    trace_count = (await db_session.execute(
        text("SELECT COUNT(*) FROM turn_traces WHERE conversation_id = :c"),
        {"c": conv_id},
    )).scalar()
    assert trace_count == 2

    await db_session.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": tid})
    await db_session.commit()


class _FakeNLUWithCost:
    """Stub NLUProvider returning deterministic NLUResult + non-zero UsageMetadata.

    Used to exercise the cost accumulation path in ConversationRunner: every
    call to classify() yields the same cost_usd value, so a test running N
    turns can assert total_cost_usd == N * cost_per_turn.
    """

    def __init__(self, cost: Decimal) -> None:
        self._cost = cost

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
            NLUResult(
                intent=Intent.GREETING,
                sentiment=Sentiment.NEUTRAL,
                confidence=0.95,
            ),
            UsageMetadata(
                model="gpt-4o-mini",
                tokens_in=100,
                tokens_out=50,
                cost_usd=self._cost,
                latency_ms=200,
            ),
        )


class _RecordingComposer:
    """Composer that records the last input and returns canned text + optional usage.

    Useful for asserting tone propagation, history, and cost accumulation.
    """

    def __init__(
        self,
        *,
        usage: UsageMetadata | None = None,
        messages: list[str] | None = None,
    ) -> None:
        self.usage = usage
        self.messages = messages or ["test_response"]
        self.last_input: ComposerInput | None = None
        self.call_count: int = 0

    async def compose(
        self, *, input: ComposerInput,
    ) -> tuple[ComposerOutput, UsageMetadata | None]:
        self.last_input = input
        self.call_count += 1
        return ComposerOutput(messages=list(self.messages)), self.usage


@pytest.mark.asyncio
async def test_total_cost_accumulates_across_turns(db_session):
    """Two consecutive turns with non-zero usage cost.

    conversation_state.total_cost_usd should reflect the sum of all
    UsageMetadata.cost_usd from the runner's turns.
    """
    tid, cid, conv_id = await _seed_tenant_with_pipeline(db_session, "test_t21_cost")

    nlu_provider = _FakeNLUWithCost(Decimal("0.000050"))
    runner = ConversationRunner(db_session, nlu_provider, CannedComposer())

    # Turn 1
    inbound1 = _make_inbound(conv_id, tid, "hola")
    await runner.run_turn(
        conversation_id=conv_id, tenant_id=tid, inbound=inbound1, turn_number=1,
    )
    await db_session.commit()

    # Turn 2
    inbound2 = _make_inbound(conv_id, tid, "qué tal")
    await runner.run_turn(
        conversation_id=conv_id, tenant_id=tid, inbound=inbound2, turn_number=2,
    )
    await db_session.commit()

    total = (await db_session.execute(
        text("SELECT total_cost_usd FROM conversation_state WHERE conversation_id = :c"),
        {"c": conv_id},
    )).scalar()
    assert total == Decimal("0.000100")

    await db_session.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": tid})
    await db_session.commit()


@pytest.mark.asyncio
async def test_total_cost_not_modified_when_usage_is_none(db_session):
    """CannedNLU returns usage=None — total_cost_usd must remain 0."""
    tid, cid, conv_id = await _seed_tenant_with_pipeline(db_session, "test_t21_no_cost")

    nlu_provider = CannedNLU(FIXTURES_DIR / "runner_qualify_to_quote.yaml")
    runner = ConversationRunner(db_session, nlu_provider, CannedComposer())

    inbound = _make_inbound(conv_id, tid, "info de la 150Z, soy de CDMX")
    await runner.run_turn(
        conversation_id=conv_id, tenant_id=tid, inbound=inbound, turn_number=1,
    )
    await db_session.commit()

    total = (await db_session.execute(
        text("SELECT total_cost_usd FROM conversation_state WHERE conversation_id = :c"),
        {"c": conv_id},
    )).scalar()
    assert total == Decimal("0")

    await db_session.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": tid})
    await db_session.commit()


# ============================================================================
# T22: tone loaded from tenant_branding.voice
# ============================================================================
@pytest.mark.asyncio
async def test_runner_loads_tone_from_tenant_branding(db_session):
    """T22: voice JSONB is loaded into a Tone and passed to the composer."""
    tid, cid, conv_id = await _seed_tenant_with_pipeline(db_session, "test_t22_tone")
    voice = {
        "register": "informal_mexicano",
        "use_emojis": "frequent",
        "max_words_per_message": 30,
        "bot_name": "Dinamo",
    }
    await db_session.execute(
        text(
            "INSERT INTO tenant_branding (tenant_id, bot_name, voice) "
            "VALUES (:t, :bn, :v\\:\\:jsonb)"
        ),
        {"t": tid, "bn": "Dinamo", "v": json.dumps(voice)},
    )
    await db_session.commit()

    composer = _RecordingComposer()
    nlu_provider = CannedNLU(FIXTURES_DIR / "runner_qualify_to_quote.yaml")
    runner = ConversationRunner(db_session, nlu_provider, composer)

    inbound = _make_inbound(conv_id, tid, "info de la 150Z, soy de CDMX")
    await runner.run_turn(
        conversation_id=conv_id, tenant_id=tid, inbound=inbound, turn_number=1,
    )
    await db_session.commit()

    # The CannedNLU yields intent=ask_info, no fields are missing relative to
    # what NLU extracted, so action could be ask_field/lookup_faq/clarification.
    # Either way action ∈ COMPOSED_ACTIONS so the composer must have been called.
    assert composer.call_count == 1
    assert composer.last_input is not None
    assert composer.last_input.tone.bot_name == "Dinamo"
    assert composer.last_input.tone.register == "informal_mexicano"
    assert composer.last_input.tone.use_emojis == "frequent"
    assert composer.last_input.tone.max_words_per_message == 30

    await db_session.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": tid})
    await db_session.commit()


# ============================================================================
# T23: composer is invoked for COMPOSED_ACTIONS inside 24h
# ============================================================================
@pytest.mark.asyncio
async def test_runner_invokes_composer_for_composed_action(db_session):
    """T23: when action is in COMPOSED_ACTIONS and inside 24h, composer is called."""
    tid, cid, conv_id = await _seed_tenant_with_pipeline(db_session, "test_t23_compose")

    composer = _RecordingComposer(messages=["hola desde el composer"])
    nlu_provider = CannedNLU(FIXTURES_DIR / "runner_qualify_to_quote.yaml")
    runner = ConversationRunner(db_session, nlu_provider, composer)

    inbound = _make_inbound(conv_id, tid, "info de la 150Z, soy de CDMX")
    trace = await runner.run_turn(
        conversation_id=conv_id, tenant_id=tid, inbound=inbound, turn_number=1,
    )
    await db_session.commit()

    assert composer.call_count == 1
    # Turn-trace columns should reflect the composer's input/output.
    assert trace.composer_input is not None
    # composer_output JSONB carries the full ComposerOutput dump; new optional
    # fields (Phase 3c.2: pending_confirmation_set) appear here as None.
    assert trace.composer_output == {
        "messages": ["hola desde el composer"],
        "pending_confirmation_set": None,
    }
    assert trace.outbound_messages == ["hola desde el composer"]
    # The composer received the per-turn extracted_data (from NLU).
    assert composer.last_input is not None
    assert "interes_producto" in composer.last_input.extracted_data

    # No human handoff was created.
    handoff_count = (await db_session.execute(
        text("SELECT COUNT(*) FROM human_handoffs WHERE conversation_id = :c"),
        {"c": conv_id},
    )).scalar()
    assert handoff_count == 0

    await db_session.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": tid})
    await db_session.commit()


# ============================================================================
# T23 + T24: outside 24h → no compose, handoff row, HUMAN_HANDOFF_REQUESTED
# ============================================================================
@pytest.mark.asyncio
async def test_runner_24h_handoff_creates_row_no_compose(db_session):
    """T23+T24: last_activity_at = now-25h → no compose; HUMAN_HANDOFF_REQUESTED."""
    tid, cid, conv_id = await _seed_tenant_with_pipeline(db_session, "test_t24_24h")

    # Backdate last_activity_at to 25h ago.
    twenty_five_hours_ago = datetime.now(UTC) - timedelta(hours=25)
    await db_session.execute(
        text("UPDATE conversations SET last_activity_at = :ts WHERE id = :cid"),
        {"ts": twenty_five_hours_ago, "cid": conv_id},
    )
    await db_session.commit()

    composer = _RecordingComposer()
    nlu_provider = CannedNLU(FIXTURES_DIR / "runner_qualify_to_quote.yaml")
    runner = ConversationRunner(db_session, nlu_provider, composer)

    inbound = _make_inbound(conv_id, tid, "info de la 150Z, soy de CDMX")
    trace = await runner.run_turn(
        conversation_id=conv_id, tenant_id=tid, inbound=inbound, turn_number=1,
    )
    await db_session.commit()

    # Composer must NOT have been called.
    assert composer.call_count == 0
    # Trace has no composer fields.
    assert trace.composer_input is None
    assert trace.composer_output is None
    assert trace.outbound_messages is None

    # human_handoffs row created with reason='outside_24h_window'.
    rows = (await db_session.execute(
        text(
            "SELECT reason, status FROM human_handoffs "
            "WHERE conversation_id = :c"
        ),
        {"c": conv_id},
    )).fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "outside_24h_window"
    assert rows[0][1] == "pending"

    # HUMAN_HANDOFF_REQUESTED event emitted.
    event_payload = (await db_session.execute(
        text(
            "SELECT payload FROM events "
            "WHERE conversation_id = :c AND type = 'human_handoff_requested'"
        ),
        {"c": conv_id},
    )).scalar()
    assert event_payload is not None
    assert event_payload["reason"] == "outside_24h_window"

    await db_session.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": tid})
    await db_session.commit()


# ============================================================================
# T23: composer fallback → handoff with reason='composer_failed'
# ============================================================================
@pytest.mark.asyncio
async def test_runner_composer_fallback_creates_handoff(db_session):
    """T23: composer_usage.fallback_used=True → human_handoff with reason='composer_failed'."""
    tid, cid, conv_id = await _seed_tenant_with_pipeline(db_session, "test_t23_fallback")

    fallback_usage = UsageMetadata(
        model="gpt-4o",
        tokens_in=200,
        tokens_out=20,
        cost_usd=Decimal("0.000200"),
        latency_ms=500,
        fallback_used=True,
    )
    composer = _RecordingComposer(usage=fallback_usage, messages=["[canned fallback]"])
    nlu_provider = CannedNLU(FIXTURES_DIR / "runner_qualify_to_quote.yaml")
    runner = ConversationRunner(db_session, nlu_provider, composer)

    inbound = _make_inbound(conv_id, tid, "info de la 150Z, soy de CDMX")
    await runner.run_turn(
        conversation_id=conv_id, tenant_id=tid, inbound=inbound, turn_number=1,
    )
    await db_session.commit()

    rows = (await db_session.execute(
        text(
            "SELECT reason, status FROM human_handoffs "
            "WHERE conversation_id = :c"
        ),
        {"c": conv_id},
    )).fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "composer_failed"
    assert rows[0][1] == "pending"

    # ERROR_OCCURRED event should have payload {"where":"composer", "fallback":"canned"}.
    event_payload = (await db_session.execute(
        text(
            "SELECT payload FROM events "
            "WHERE conversation_id = :c AND type = 'error_occurred' "
            "ORDER BY occurred_at DESC LIMIT 1"
        ),
        {"c": conv_id},
    )).scalar()
    assert event_payload is not None
    assert event_payload["where"] == "composer"
    assert event_payload["fallback"] == "canned"

    await db_session.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": tid})
    await db_session.commit()


# ============================================================================
# T23: total_cost_usd accumulates BOTH nlu and composer cost
# ============================================================================
@pytest.mark.asyncio
async def test_runner_total_cost_includes_composer(db_session):
    """T23: conversation_state.total_cost_usd accumulates both nlu+composer."""
    tid, cid, conv_id = await _seed_tenant_with_pipeline(db_session, "test_t23_cost")

    composer_usage = UsageMetadata(
        model="gpt-4o",
        tokens_in=300,
        tokens_out=80,
        cost_usd=Decimal("0.000300"),
        latency_ms=400,
    )
    composer = _RecordingComposer(usage=composer_usage)
    nlu_provider = _FakeNLUWithCost(Decimal("0.000050"))
    runner = ConversationRunner(db_session, nlu_provider, composer)

    inbound = _make_inbound(conv_id, tid, "hola")
    await runner.run_turn(
        conversation_id=conv_id, tenant_id=tid, inbound=inbound, turn_number=1,
    )
    await db_session.commit()

    total = (await db_session.execute(
        text("SELECT total_cost_usd FROM conversation_state WHERE conversation_id = :c"),
        {"c": conv_id},
    )).scalar()
    # 0.000050 (nlu) + 0.000300 (composer) = 0.000350
    assert total == Decimal("0.000350")

    await db_session.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": tid})
    await db_session.commit()


# ============================================================================
# Phase 3c.2 — Parallel NLU + Vision integration (T20)
# ============================================================================

@pytest.mark.asyncio
async def test_runner_runs_vision_in_parallel_when_image_attached(
    db_session, monkeypatch,
):
    """Image attachment with resolved URL + openai_api_key → Vision fires.

    Verifies the asyncio.gather branch:
      - NLU result still drives state extraction
      - Vision result populates turn_traces.vision_cost_usd / vision_latency_ms
      - vision_cost_usd lands in conversation_state.total_cost_usd
    """
    import json as _json

    import respx
    from httpx import Response

    from atendia.contracts.message import Attachment

    tid, cid, conv_id = await _seed_tenant_with_pipeline(
        db_session, "test_t20_vision_parallel",
    )
    monkeypatch.setenv("ATENDIA_V2_OPENAI_API_KEY", "sk-test-vision")
    from atendia.config import get_settings
    get_settings.cache_clear()

    vision_payload = _json.dumps({
        "category": "ine",
        "confidence": 0.92,
        "metadata": {
            "ambos_lados": True, "legible": True,
            "fecha_iso": None, "institucion": None,
            "modelo": None, "notas": None,
        },
    })
    with respx.mock(assert_all_called=True) as router:
        router.post("https://api.openai.com/v1/chat/completions").mock(
            return_value=Response(200, json={
                "id": "chatcmpl-vision",
                "choices": [{
                    "message": {"role": "assistant", "content": vision_payload},
                    "finish_reason": "stop",
                }],
                "usage": {"prompt_tokens": 1500, "completion_tokens": 80,
                          "total_tokens": 1580},
            }),
        )

        runner = ConversationRunner(
            db_session, _FakeNLUWithCost(Decimal("0.000050")), CannedComposer(),
        )

        inbound = _make_inbound(conv_id, tid, "aquí va mi INE")
        inbound.attachments = [Attachment(
            media_id="MEDIA_X", mime_type="image/jpeg",
            url="https://lookaside.fbsbx.com/test_ine",
        )]
        trace = await runner.run_turn(
            conversation_id=conv_id, tenant_id=tid, inbound=inbound, turn_number=1,
        )
        await db_session.commit()

    assert trace.vision_cost_usd is not None
    assert trace.vision_cost_usd > 0
    assert trace.vision_latency_ms is not None
    assert trace.vision_latency_ms >= 0

    total = (await db_session.execute(
        text("SELECT total_cost_usd FROM conversation_state WHERE conversation_id = :c"),
        {"c": conv_id},
    )).scalar()
    assert total > Decimal("0.000050")  # NLU 0.000050 + non-zero Vision

    await db_session.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": tid})
    await db_session.commit()
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_runner_skips_vision_when_no_image_attachment(db_session, monkeypatch):
    """Text-only inbound: NLU runs, Vision does NOT — trace has no vision data."""
    tid, cid, conv_id = await _seed_tenant_with_pipeline(
        db_session, "test_t20_no_vision",
    )
    monkeypatch.setenv("ATENDIA_V2_OPENAI_API_KEY", "sk-test-no-vision")
    from atendia.config import get_settings
    get_settings.cache_clear()

    runner = ConversationRunner(
        db_session, _FakeNLUWithCost(Decimal("0.000050")), CannedComposer(),
    )
    inbound = _make_inbound(conv_id, tid, "hola")
    trace = await runner.run_turn(
        conversation_id=conv_id, tenant_id=tid, inbound=inbound, turn_number=1,
    )
    await db_session.commit()

    assert trace.vision_cost_usd is None
    assert trace.vision_latency_ms is None

    await db_session.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": tid})
    await db_session.commit()
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_runner_persists_flow_mode_and_loads_brand_facts(
    db_session, monkeypatch,
):
    """T21 — flow_mode lands on TurnTrace, brand_facts reaches ComposerInput.

    With default pipeline rules (no `flow_mode_rules` authored) every turn
    should pick FlowMode.SUPPORT via the always-fallback. brand_facts come
    from tenant_branding.default_messages JSONB.
    """
    tid, cid, conv_id = await _seed_tenant_with_pipeline(
        db_session, "test_t21_flow_mode_persist",
    )
    # Seed brand_facts the way T23 will eventually populate them.
    await db_session.execute(
        text("INSERT INTO tenant_branding (tenant_id, bot_name, voice, default_messages) "
             "VALUES (:t, 'Dinamo', :v\\:\\:jsonb, :d\\:\\:jsonb)"),
        {
            "t": tid,
            "v": json.dumps({"register": "informal_mexicano"}),
            "d": json.dumps({"brand_facts": {
                "address": "Benito Juárez 801",
                "human_agent_name": "Francisco",
            }}),
        },
    )
    await db_session.commit()

    composer = _RecordingComposer()
    runner = ConversationRunner(
        db_session, _FakeNLUWithCost(Decimal("0.000050")), composer,
    )
    inbound = _make_inbound(conv_id, tid, "hola")
    trace = await runner.run_turn(
        conversation_id=conv_id, tenant_id=tid, inbound=inbound, turn_number=1,
    )
    await db_session.commit()

    # Default pipeline rules → SUPPORT.
    assert trace.flow_mode == "SUPPORT"
    # Composer received the live brand_facts.
    assert composer.last_input is not None
    assert composer.last_input.flow_mode.value == "SUPPORT"
    assert composer.last_input.brand_facts == {
        "address": "Benito Juárez 801",
        "human_agent_name": "Francisco",
    }
    assert composer.last_input.turn_number == 1

    await db_session.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": tid})
    await db_session.commit()


@pytest.mark.asyncio
async def test_runner_picks_flow_mode_per_authored_rules(db_session):
    """Tenant authors a custom flow_mode_rules list → router applies it.

    Seeds a pipeline whose definition JSONB includes a flow_mode_rules entry
    that triggers RETENTION on the keyword 'gracias'. Verifies the runner
    threads the rules through pick_flow_mode and persists RETENTION.
    """
    pipeline_with_rules = {
        **PIPELINE_QUALIFY_QUOTE,
        "flow_mode_rules": [
            {"id": "retain_on_gracias", "trigger": {
                "type": "keyword_in_text", "list": ["gracias"]},
                "mode": "RETENTION"},
            {"id": "always_support", "trigger": {"type": "always"}, "mode": "SUPPORT"},
        ],
    }
    tid = (await db_session.execute(
        text("INSERT INTO tenants (name) VALUES (:n) RETURNING id"),
        {"n": "test_t21_authored_rules"},
    )).scalar()
    await db_session.execute(
        text("INSERT INTO tenant_pipelines (tenant_id, version, definition, active) "
             "VALUES (:t, 1, :d\\:\\:jsonb, true)"),
        {"t": tid, "d": json.dumps(pipeline_with_rules)},
    )
    cid = (await db_session.execute(
        text("INSERT INTO customers (tenant_id, phone_e164) "
             "VALUES (:t, '+5215555550037') RETURNING id"),
        {"t": tid},
    )).scalar()
    conv_id = (await db_session.execute(
        text("INSERT INTO conversations (tenant_id, customer_id, current_stage) "
             "VALUES (:t, :c, 'qualify') RETURNING id"),
        {"t": tid, "c": cid},
    )).scalar()
    await db_session.execute(
        text("INSERT INTO conversation_state (conversation_id) VALUES (:c)"),
        {"c": conv_id},
    )
    await db_session.commit()

    runner = ConversationRunner(
        db_session, _FakeNLUWithCost(Decimal("0.000050")), CannedComposer(),
    )
    trace = await runner.run_turn(
        conversation_id=conv_id, tenant_id=tid,
        inbound=_make_inbound(conv_id, tid, "muchas gracias por la info"),
        turn_number=1,
    )
    await db_session.commit()

    assert trace.flow_mode == "RETENTION"

    await db_session.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": tid})
    await db_session.commit()


# ============================================================================
# Phase 3c.2 — pending_confirmation binary handling (T22)
# ============================================================================

async def _seed_pending_confirmation(
    db_session, tenant_name: str, pending_key: str,
) -> tuple:
    """Seed a tenant + conversation whose state already has the slot set.

    Mimics the situation post-composer turn N where the LLM raised a binary
    question; on turn N+1 the user replies sí/no and the runner resolves it.
    """
    tid, cid, conv_id = await _seed_tenant_with_pipeline(db_session, tenant_name)
    await db_session.execute(
        text("UPDATE conversation_state SET pending_confirmation = :pc "
             "WHERE conversation_id = :cid"),
        {"pc": pending_key, "cid": conv_id},
    )
    await db_session.commit()
    return tid, cid, conv_id


@pytest.mark.asyncio
async def test_pending_confirmation_si_assigns_tipo_credito(db_session):
    """User replies 'sí' to is_nomina_tarjeta → fields written, pc cleared."""
    tid, cid, conv_id = await _seed_pending_confirmation(
        db_session, "test_t22_si_nomina", "is_nomina_tarjeta",
    )
    runner = ConversationRunner(
        db_session, _FakeNLUWithCost(Decimal("0.000050")), CannedComposer(),
    )
    await runner.run_turn(
        conversation_id=conv_id, tenant_id=tid,
        inbound=_make_inbound(conv_id, tid, "sí"), turn_number=2,
    )
    await db_session.commit()

    state = (await db_session.execute(
        text("SELECT extracted_data, pending_confirmation FROM conversation_state "
             "WHERE conversation_id = :c"),
        {"c": conv_id},
    )).fetchone()
    extracted, pc = state
    assert pc is None
    assert extracted["tipo_credito"]["value"] == "Nómina Tarjeta"
    assert extracted["plan_credito"]["value"] == "10%"

    await db_session.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": tid})
    await db_session.commit()


@pytest.mark.asyncio
async def test_pending_confirmation_no_to_negocio_sat_assigns_sin_comprobantes(
    db_session,
):
    """is_negocio_sat + 'no' → tipo_credito=Sin Comprobantes, plan_credito=20%.

    The negative branch is the only path that ALSO writes fields (the others
    leave state alone for the LLM to re-prompt).
    """
    tid, cid, conv_id = await _seed_pending_confirmation(
        db_session, "test_t22_no_negocio", "is_negocio_sat",
    )
    runner = ConversationRunner(
        db_session, _FakeNLUWithCost(Decimal("0.000050")), CannedComposer(),
    )
    await runner.run_turn(
        conversation_id=conv_id, tenant_id=tid,
        inbound=_make_inbound(conv_id, tid, "nel"), turn_number=2,
    )
    await db_session.commit()

    state = (await db_session.execute(
        text("SELECT extracted_data, pending_confirmation FROM conversation_state "
             "WHERE conversation_id = :c"),
        {"c": conv_id},
    )).fetchone()
    extracted, pc = state
    assert pc is None
    assert extracted["tipo_credito"]["value"] == "Sin Comprobantes"
    assert extracted["plan_credito"]["value"] == "20%"

    await db_session.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": tid})
    await db_session.commit()


@pytest.mark.asyncio
async def test_pending_confirmation_ambiguous_reply_does_not_clear(db_session):
    """User replies with free text → runner doesn't try to interpret; pc stays.

    'Sí pero también quiero saber otra cosa' is NOT in _AFFIRMATIVE (it's
    multi-word) so the binary handler punts and the slot is preserved.
    """
    tid, cid, conv_id = await _seed_pending_confirmation(
        db_session, "test_t22_ambiguous", "is_nomina_tarjeta",
    )
    runner = ConversationRunner(
        db_session, _FakeNLUWithCost(Decimal("0.000050")), CannedComposer(),
    )
    await runner.run_turn(
        conversation_id=conv_id, tenant_id=tid,
        inbound=_make_inbound(conv_id, tid, "sí pero también algo más"),
        turn_number=2,
    )
    await db_session.commit()

    pc = (await db_session.execute(
        text("SELECT pending_confirmation FROM conversation_state "
             "WHERE conversation_id = :c"),
        {"c": conv_id},
    )).scalar()
    assert pc == "is_nomina_tarjeta"

    await db_session.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": tid})
    await db_session.commit()


@pytest.mark.asyncio
async def test_composer_pending_confirmation_set_persists(db_session):
    """Composer raises pending_confirmation_set → runner writes it to state."""
    from atendia.runner.composer_protocol import ComposerOutput

    class _ComposerThatRaisesBinary:
        async def compose(self, *, input):
            return (
                ComposerOutput(
                    messages=["¿Te dan recibos?"],
                    pending_confirmation_set="is_nomina_recibos",
                ),
                None,
            )

    tid, cid, conv_id = await _seed_tenant_with_pipeline(
        db_session, "test_t22_composer_set",
    )
    runner = ConversationRunner(
        db_session,
        _FakeNLUWithCost(Decimal("0.000050")),
        _ComposerThatRaisesBinary(),
    )
    await runner.run_turn(
        conversation_id=conv_id, tenant_id=tid,
        inbound=_make_inbound(conv_id, tid, "deposito"), turn_number=1,
    )
    await db_session.commit()

    pc = (await db_session.execute(
        text("SELECT pending_confirmation FROM conversation_state "
             "WHERE conversation_id = :c"),
        {"c": conv_id},
    )).scalar()
    assert pc == "is_nomina_recibos"

    await db_session.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": tid})
    await db_session.commit()


@pytest.mark.asyncio
async def test_runner_swallows_vision_failure_and_keeps_nlu(db_session, monkeypatch):
    """Vision endpoint 500s → ERROR_OCCURRED event, NLU result still drives turn."""
    import respx
    from httpx import Response

    from atendia.contracts.message import Attachment

    tid, cid, conv_id = await _seed_tenant_with_pipeline(
        db_session, "test_t20_vision_failure",
    )
    monkeypatch.setenv("ATENDIA_V2_OPENAI_API_KEY", "sk-test-vision-fail")
    from atendia.config import get_settings
    get_settings.cache_clear()

    with respx.mock:
        respx.post("https://api.openai.com/v1/chat/completions").mock(
            return_value=Response(500, json={"error": "internal"}),
        )

        runner = ConversationRunner(
            db_session, _FakeNLUWithCost(Decimal("0.000050")), CannedComposer(),
        )
        inbound = _make_inbound(conv_id, tid, "aquí va")
        inbound.attachments = [Attachment(
            media_id="MEDIA_FAIL", mime_type="image/jpeg",
            url="https://lookaside.fbsbx.com/will_500",
        )]
        trace = await runner.run_turn(
            conversation_id=conv_id, tenant_id=tid, inbound=inbound, turn_number=1,
        )
        await db_session.commit()

    assert trace.nlu_cost_usd == Decimal("0.000050")
    assert trace.vision_cost_usd is None

    err_rows = (await db_session.execute(
        text("SELECT payload FROM events "
             "WHERE conversation_id = :c AND type = 'error_occurred'"),
        {"c": conv_id},
    )).fetchall()
    payloads = [r[0] for r in err_rows]
    assert any(p.get("where") == "vision" for p in payloads)

    await db_session.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": tid})
    await db_session.commit()
    get_settings.cache_clear()
