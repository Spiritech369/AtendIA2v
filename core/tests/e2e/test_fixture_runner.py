import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest
import yaml
from sqlalchemy import text

from atendia.contracts.message import Message, MessageDirection
from atendia.runner.conversation_runner import ConversationRunner
from atendia.runner.nlu_canned import CannedNLU

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "conversations"


def _fixture_paths():
    return sorted(FIXTURES_DIR.glob("*.yaml"))


@pytest.mark.parametrize(
    "fixture_path",
    _fixture_paths(),
    ids=lambda p: p.stem,
)
@pytest.mark.asyncio
async def test_fixture_runs_to_expected_states(fixture_path, db_session, tmp_path):
    spec = yaml.safe_load(fixture_path.read_text(encoding="utf-8"))

    # Seed tenant + pipeline
    tid = (
        await db_session.execute(
            text("INSERT INTO tenants (name) VALUES (:n) RETURNING id"),
            {"n": spec["tenant"]["name"]},
        )
    ).scalar()
    await db_session.execute(
        text(
            "INSERT INTO tenant_pipelines (tenant_id, version, definition, active) "
            "VALUES (:t, :v, :d\\:\\:jsonb, true)"
        ),
        {
            "t": tid,
            "v": spec["pipeline"]["version"],
            "d": json.dumps(spec["pipeline"]),
        },
    )

    # Seed catalog if any
    for item in spec.get("catalog") or []:
        await db_session.execute(
            text(
                "INSERT INTO tenant_catalogs (tenant_id, sku, name, attrs) "
                "VALUES (:t, :s, :n, :a\\:\\:jsonb)"
            ),
            {
                "t": tid,
                "s": item["sku"],
                "n": item["name"],
                "a": json.dumps(item.get("attrs") or {}),
            },
        )

    # Seed customer + conversation pinned to first stage
    cid = (
        await db_session.execute(
            text(
                "INSERT INTO customers (tenant_id, phone_e164) VALUES (:t, '+5215555550042') RETURNING id"
            ),
            {"t": tid},
        )
    ).scalar()
    initial_stage = spec["pipeline"]["stages"][0]["id"]
    conv_id = (
        await db_session.execute(
            text(
                "INSERT INTO conversations (tenant_id, customer_id, current_stage) "
                "VALUES (:t, :c, :s) RETURNING id"
            ),
            {"t": tid, "c": cid, "s": initial_stage},
        )
    ).scalar()
    await db_session.execute(
        text("INSERT INTO conversation_state (conversation_id) VALUES (:c)"),
        {"c": conv_id},
    )
    await db_session.commit()

    # Build inline canned NLU file from spec turns
    inline_nlu = {"nlu_results": [t["nlu"] for t in spec["turns"]]}
    inline_path = tmp_path / f"{fixture_path.stem}.nlu.yaml"
    inline_path.write_text(yaml.safe_dump(inline_nlu), encoding="utf-8")

    from atendia.runner.composer_canned import CannedComposer

    runner = ConversationRunner(db_session, CannedNLU(inline_path), CannedComposer())

    for i, turn in enumerate(spec["turns"]):
        msg = Message(
            id=str(uuid4()),
            conversation_id=str(conv_id),
            tenant_id=str(tid),
            direction=MessageDirection.INBOUND,
            text=turn["inbound"],
            sent_at=datetime.now(timezone.utc),
        )
        trace = await runner.run_turn(
            conversation_id=conv_id,
            tenant_id=tid,
            inbound=msg,
            turn_number=i,
        )
        await db_session.commit()
        expected_stage = turn["expected"]["next_stage"]
        assert trace.state_after["current_stage"] == expected_stage, (
            f"{fixture_path.stem} turn {i} ({turn['inbound']!r}): "
            f"expected stage {expected_stage!r}, got {trace.state_after['current_stage']!r}"
        )

    # Cleanup
    await db_session.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": tid})
    await db_session.commit()
