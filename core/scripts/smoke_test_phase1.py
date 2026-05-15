"""Phase 1 smoke test — runs the ConversationRunner end-to-end against the v2 DB.

Usage (from `core/`):
    uv run python scripts/smoke_test_phase1.py

Expected: prints turn-by-turn state transitions and ends with
"OK — phase 1 smoke test passed".
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from atendia.config import get_settings
from atendia.contracts.message import Message, MessageDirection
from atendia.runner.conversation_runner import ConversationRunner
from atendia.runner.nlu_canned import CannedNLU

PIPELINE_DEF = {
    "version": 1,
    "stages": [
        {
            "id": "greeting",
            "actions_allowed": ["greet", "ask_field"],
            "transitions": [
                {"to": "qualify", "when": "intent in [ask_info, ask_price]"},
            ],
        },
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
            "transitions": [
                {"to": "close", "when": "intent == buy"},
            ],
        },
        {
            "id": "close",
            "actions_allowed": ["close"],
            "transitions": [],
        },
    ],
    "tone": {"register": "informal_mexicano"},
    "fallback": "escalate_to_human",
}


SMOKE_NLU_FIXTURE = """\
nlu_results:
  - intent: greeting
    entities: {}
    sentiment: neutral
    confidence: 0.95
    ambiguities: []
  - intent: ask_info
    entities:
      interes_producto: { value: "150Z", confidence: 0.95, source_turn: 1 }
      ciudad: { value: "CDMX", confidence: 0.95, source_turn: 1 }
    sentiment: neutral
    confidence: 0.95
    ambiguities: []
  - intent: ask_price
    entities: {}
    sentiment: neutral
    confidence: 0.95
    ambiguities: []
  - intent: buy
    entities: {}
    sentiment: positive
    confidence: 0.95
    ambiguities: []
"""


TURN_TEXTS = [
    "hola",
    "info de la 150Z, soy de CDMX",
    "cuánto cuesta?",
    "la quiero",
]


async def main() -> int:
    engine = create_async_engine(get_settings().database_url)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    fixture_path = Path(__file__).parent / "_smoke_nlu.yaml"
    fixture_path.write_text(SMOKE_NLU_FIXTURE, encoding="utf-8")

    async with Session() as session:
        # Seed tenant + pipeline + customer + conversation
        tenant_name = f"smoke_phase1_{uuid4().hex[:8]}"
        tid = (
            await session.execute(
                text("INSERT INTO tenants (name) VALUES (:n) RETURNING id"),
                {"n": tenant_name},
            )
        ).scalar()
        await session.execute(
            text(
                "INSERT INTO tenant_pipelines (tenant_id, version, definition, active) "
                "VALUES (:t, 1, :d\\:\\:jsonb, true)"
            ),
            {"t": tid, "d": json.dumps(PIPELINE_DEF)},
        )
        cid = (
            await session.execute(
                text(
                    "INSERT INTO customers (tenant_id, phone_e164) VALUES (:t, '+5215555550039') RETURNING id"
                ),
                {"t": tid},
            )
        ).scalar()
        conv_id = (
            await session.execute(
                text(
                    "INSERT INTO conversations (tenant_id, customer_id, current_stage) "
                    "VALUES (:t, :c, 'greeting') RETURNING id"
                ),
                {"t": tid, "c": cid},
            )
        ).scalar()
        await session.execute(
            text("INSERT INTO conversation_state (conversation_id) VALUES (:c)"),
            {"c": conv_id},
        )
        await session.commit()

        print(f"Tenant {tenant_name} ({tid}) seeded with 4-stage pipeline")

        from atendia.runner.composer_canned import CannedComposer

        runner = ConversationRunner(session, CannedNLU(fixture_path), CannedComposer())
        for i, text_msg in enumerate(TURN_TEXTS, start=1):
            inbound = Message(
                id=str(uuid4()),
                conversation_id=str(conv_id),
                tenant_id=str(tid),
                direction=MessageDirection.INBOUND,
                text=text_msg,
                sent_at=datetime.now(timezone.utc),
            )
            trace = await runner.run_turn(
                conversation_id=conv_id,
                tenant_id=tid,
                inbound=inbound,
                turn_number=i,
            )
            await session.commit()
            transition = trace.stage_transition or "(no transition)"
            print(f"Turn {i}: {text_msg!r} → {trace.state_after['current_stage']} ({transition})")

        # Print events summary
        events = (
            await session.execute(
                text(
                    "SELECT type, payload FROM events WHERE conversation_id = :c "
                    "ORDER BY occurred_at"
                ),
                {"c": conv_id},
            )
        ).fetchall()
        print(f"Events emitted: {len(events)}")
        for evt_type, payload in events:
            print(f"  - {evt_type}: {payload}")

        # Cleanup
        await session.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": tid})
        await session.commit()

    fixture_path.unlink(missing_ok=True)
    await engine.dispose()

    final_stage_ok = trace.state_after["current_stage"] == "close"
    if not final_stage_ok:
        print(f"FAIL — expected final stage 'close', got {trace.state_after['current_stage']!r}")
        return 1

    print("OK — phase 1 smoke test passed")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
