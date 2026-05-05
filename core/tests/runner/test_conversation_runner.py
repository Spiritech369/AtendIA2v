import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text

from atendia.contracts.message import Message, MessageDirection
from atendia.runner.conversation_runner import ConversationRunner
from atendia.runner.nlu_canned import CannedNLU


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
        sent_at=datetime.now(timezone.utc),
    )


@pytest.mark.asyncio
async def test_runner_extracts_fields_then_transitions_to_quote(db_session):
    tid, cid, conv_id = await _seed_tenant_with_pipeline(db_session, "test_t37_main")

    nlu_provider = CannedNLU(FIXTURES_DIR / "runner_qualify_to_quote.yaml")
    runner = ConversationRunner(db_session, nlu_provider)

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
