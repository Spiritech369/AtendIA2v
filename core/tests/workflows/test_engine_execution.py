"""Per-node execution tests against a real Postgres.

Redis side-effects are stubbed via the ``stub_outbound_enqueue`` /
``stub_step_enqueue`` fixtures (see ``conftest.py``).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from atendia.workflows.engine import (
    definition_for_steps,
    execute_workflow,
)


@pytest.mark.asyncio
async def test_message_node_enqueues_outbound(
    db_session,
    seed_tenant_factory,
    insert_workflow,
    stub_outbound_enqueue,
) -> None:
    seed = await seed_tenant_factory()
    defn = definition_for_steps(
        "message_received",
        [{"type": "message", "config": {"text": "Hola Ana!"}}],
    )
    _, exec_id = await insert_workflow(
        tenant_id=seed["tenant_id"],
        conversation_id=seed["conversation_id"],
        definition=defn,
    )

    await execute_workflow(db_session, exec_id)
    await db_session.commit()

    assert len(stub_outbound_enqueue) == 1
    msg = stub_outbound_enqueue[0]
    assert msg.text == "Hola Ana!"
    assert msg.tenant_id == seed["tenant_id"]
    # Idempotency key includes execution + node id; arq will dedupe replays.
    assert str(exec_id) in msg.idempotency_key

    status = (
        await db_session.execute(
            text("SELECT status FROM workflow_executions WHERE id = :i"),
            {"i": exec_id},
        )
    ).scalar()
    assert status == "completed"


@pytest.mark.asyncio
async def test_message_node_outside_24h_window_fails(
    db_session,
    seed_tenant_factory,
    insert_workflow,
    stub_outbound_enqueue,
) -> None:
    seed = await seed_tenant_factory(with_recent_inbound=False)
    # Insert a stale inbound (>24h ago).
    await db_session.execute(
        text(
            "INSERT INTO messages (conversation_id, tenant_id, direction, text, sent_at) "
            "VALUES (:c, :t, 'inbound', 'old', :s)"
        ),
        {
            "c": seed["conversation_id"],
            "t": seed["tenant_id"],
            "s": datetime.now(UTC) - timedelta(hours=25),
        },
    )
    await db_session.commit()

    defn = definition_for_steps(
        "message_received",
        [{"type": "message", "config": {"text": "hi"}}],
    )
    _, exec_id = await insert_workflow(
        tenant_id=seed["tenant_id"],
        conversation_id=seed["conversation_id"],
        definition=defn,
    )

    await execute_workflow(db_session, exec_id)
    await db_session.commit()

    assert stub_outbound_enqueue == []
    row = (
        await db_session.execute(
            text("SELECT status, error_code FROM workflow_executions WHERE id = :i"),
            {"i": exec_id},
        )
    ).one()
    assert row.status == "failed"
    assert row.error_code == "OUTSIDE_24H_WINDOW"


@pytest.mark.asyncio
async def test_message_node_idempotent_on_retry(
    db_session,
    seed_tenant_factory,
    insert_workflow,
    stub_outbound_enqueue,
) -> None:
    seed = await seed_tenant_factory()
    defn = definition_for_steps(
        "message_received",
        [{"type": "message", "config": {"text": "x"}}],
    )
    _, exec_id = await insert_workflow(
        tenant_id=seed["tenant_id"],
        conversation_id=seed["conversation_id"],
        definition=defn,
    )

    await execute_workflow(db_session, exec_id)
    await db_session.commit()
    # Re-run as if retry: WorkflowActionRun unique index dedupes.
    await execute_workflow(db_session, exec_id, start_node_id="action_1")
    await db_session.commit()

    assert len(stub_outbound_enqueue) == 1


@pytest.mark.asyncio
async def test_move_stage_updates_conversation_and_state(
    db_session,
    seed_tenant_factory,
    insert_workflow,
) -> None:
    seed = await seed_tenant_factory(pipeline_stages=["lead", "won"])
    defn = definition_for_steps(
        "message_received",
        [{"type": "move_stage", "config": {"stage_id": "won"}}],
    )
    _, exec_id = await insert_workflow(
        tenant_id=seed["tenant_id"],
        conversation_id=seed["conversation_id"],
        definition=defn,
    )

    await execute_workflow(db_session, exec_id)
    await db_session.commit()

    stage = (
        await db_session.execute(
            text("SELECT current_stage FROM conversations WHERE id = :c"),
            {"c": seed["conversation_id"]},
        )
    ).scalar()
    assert stage == "won"


@pytest.mark.asyncio
async def test_assign_agent_rejects_cross_tenant(
    db_session,
    seed_tenant_factory,
    insert_workflow,
) -> None:
    a = await seed_tenant_factory(agent_count=1)
    b = await seed_tenant_factory()
    defn = definition_for_steps(
        "message_received",
        [{"type": "assign_agent", "config": {"agent_id": a["agent_ids"][0]}}],
    )
    _, exec_id = await insert_workflow(
        tenant_id=b["tenant_id"],
        conversation_id=b["conversation_id"],
        definition=defn,
    )

    await execute_workflow(db_session, exec_id)
    await db_session.commit()

    row = (
        await db_session.execute(
            text("SELECT status, error_code FROM workflow_executions WHERE id = :i"),
            {"i": exec_id},
        )
    ).one()
    assert row.status == "failed"
    assert row.error_code == "UNKNOWN_AGENT"


@pytest.mark.asyncio
async def test_notify_agent_rejects_cross_tenant_user(
    db_session,
    seed_tenant_factory,
    insert_workflow,
) -> None:
    a = await seed_tenant_factory(user_role="operator")
    b = await seed_tenant_factory()
    defn = definition_for_steps(
        "message_received",
        [{"type": "notify_agent", "config": {"user_id": a["user_id"], "title": "t"}}],
    )
    _, exec_id = await insert_workflow(
        tenant_id=b["tenant_id"],
        conversation_id=b["conversation_id"],
        definition=defn,
    )

    await execute_workflow(db_session, exec_id)
    await db_session.commit()

    row = (
        await db_session.execute(
            text("SELECT status, error_code FROM workflow_executions WHERE id = :i"),
            {"i": exec_id},
        )
    ).one()
    assert row.status == "failed"
    assert row.error_code == "UNKNOWN_USER"

    notif_count = (
        await db_session.execute(
            text("SELECT count(*) FROM notifications WHERE tenant_id = :t"),
            {"t": b["tenant_id"]},
        )
    ).scalar()
    assert notif_count == 0


@pytest.mark.asyncio
async def test_notify_agent_role_target_creates_notifications(
    db_session,
    seed_tenant_factory,
    insert_workflow,
) -> None:
    seed = await seed_tenant_factory(user_role="tenant_admin")
    defn = definition_for_steps(
        "message_received",
        [{"type": "notify_agent", "config": {"role": "tenant_admin", "title": "alert"}}],
    )
    _, exec_id = await insert_workflow(
        tenant_id=seed["tenant_id"],
        conversation_id=seed["conversation_id"],
        definition=defn,
    )

    await execute_workflow(db_session, exec_id)
    await db_session.commit()

    rows = (
        await db_session.execute(
            text("SELECT user_id, title FROM notifications WHERE tenant_id = :t"),
            {"t": seed["tenant_id"]},
        )
    ).all()
    assert len(rows) == 1
    assert rows[0].title == "alert"


@pytest.mark.asyncio
async def test_update_field_merges_extracted_data(
    db_session,
    seed_tenant_factory,
    insert_workflow,
) -> None:
    seed = await seed_tenant_factory()
    defn = definition_for_steps(
        "message_received",
        [{"type": "update_field", "config": {"field": "plan_credito", "value": "36m"}}],
    )
    _, exec_id = await insert_workflow(
        tenant_id=seed["tenant_id"],
        conversation_id=seed["conversation_id"],
        definition=defn,
    )

    await execute_workflow(db_session, exec_id)
    await db_session.commit()

    extracted = (
        await db_session.execute(
            text("SELECT extracted_data FROM conversation_state WHERE conversation_id = :c"),
            {"c": seed["conversation_id"]},
        )
    ).scalar()
    assert extracted["plan_credito"]["value"] == "36m"
    assert extracted["plan_credito"]["source"] == "workflow"


@pytest.mark.asyncio
async def test_pause_bot_sets_flag(
    db_session,
    seed_tenant_factory,
    insert_workflow,
) -> None:
    seed = await seed_tenant_factory()
    defn = definition_for_steps("message_received", [{"type": "pause_bot"}])
    _, exec_id = await insert_workflow(
        tenant_id=seed["tenant_id"],
        conversation_id=seed["conversation_id"],
        definition=defn,
    )

    await execute_workflow(db_session, exec_id)
    await db_session.commit()

    paused = (
        await db_session.execute(
            text("SELECT bot_paused FROM conversation_state WHERE conversation_id = :c"),
            {"c": seed["conversation_id"]},
        )
    ).scalar()
    assert paused is True


@pytest.mark.asyncio
async def test_condition_routes_on_extracted_field(
    db_session,
    seed_tenant_factory,
    insert_workflow,
) -> None:
    seed = await seed_tenant_factory()
    # Pre-populate extracted field so the condition resolves true.
    await db_session.execute(
        text("UPDATE conversation_state SET extracted_data = :d WHERE conversation_id = :c"),
        {"c": seed["conversation_id"], "d": '{"plan":{"value":"36m"}}'},
    )
    await db_session.commit()

    defn = {
        "nodes": [
            {"id": "trigger_1", "type": "trigger"},
            {
                "id": "cond",
                "type": "condition",
                "config": {"field": "extracted.plan", "operator": "eq", "value": "36m"},
            },
            {"id": "true_branch", "type": "pause_bot"},
            {"id": "false_branch", "type": "update_field", "config": {"field": "x", "value": "y"}},
        ],
        "edges": [
            {"from": "trigger_1", "to": "cond"},
            {"from": "cond", "to": "true_branch", "label": "true"},
            {"from": "cond", "to": "false_branch", "label": "false"},
        ],
    }
    _, exec_id = await insert_workflow(
        tenant_id=seed["tenant_id"],
        conversation_id=seed["conversation_id"],
        definition=defn,
    )

    await execute_workflow(db_session, exec_id)
    await db_session.commit()

    paused = (
        await db_session.execute(
            text("SELECT bot_paused FROM conversation_state WHERE conversation_id = :c"),
            {"c": seed["conversation_id"]},
        )
    ).scalar()
    assert paused is True


@pytest.mark.asyncio
async def test_condition_resolves_customer_score(
    db_session,
    seed_tenant_factory,
    insert_workflow,
) -> None:
    seed = await seed_tenant_factory()  # score is 50 from seed
    defn = {
        "nodes": [
            {"id": "trigger_1", "type": "trigger"},
            {
                "id": "cond",
                "type": "condition",
                "config": {"field": "customer.score", "operator": "eq", "value": 50},
            },
            {"id": "yes", "type": "pause_bot"},
            {"id": "no", "type": "update_field", "config": {"field": "x", "value": "y"}},
        ],
        "edges": [
            {"from": "trigger_1", "to": "cond"},
            {"from": "cond", "to": "yes", "label": "true"},
            {"from": "cond", "to": "no", "label": "false"},
        ],
    }
    _, exec_id = await insert_workflow(
        tenant_id=seed["tenant_id"],
        conversation_id=seed["conversation_id"],
        definition=defn,
    )

    await execute_workflow(db_session, exec_id)
    await db_session.commit()

    paused = (
        await db_session.execute(
            text("SELECT bot_paused FROM conversation_state WHERE conversation_id = :c"),
            {"c": seed["conversation_id"]},
        )
    ).scalar()
    assert paused is True


@pytest.mark.asyncio
async def test_delay_pauses_and_enqueues_step(
    db_session,
    seed_tenant_factory,
    insert_workflow,
    stub_step_enqueue,
) -> None:
    seed = await seed_tenant_factory()
    defn = {
        "nodes": [
            {"id": "trigger_1", "type": "trigger"},
            {"id": "d", "type": "delay", "config": {"seconds": 60}},
            {"id": "pb", "type": "pause_bot"},
        ],
        "edges": [
            {"from": "trigger_1", "to": "d"},
            {"from": "d", "to": "pb"},
        ],
    }
    _, exec_id = await insert_workflow(
        tenant_id=seed["tenant_id"],
        conversation_id=seed["conversation_id"],
        definition=defn,
    )

    await execute_workflow(db_session, exec_id)
    await db_session.commit()

    assert len(stub_step_enqueue) == 1
    job = stub_step_enqueue[0]
    assert job["execution_id"] == exec_id
    assert job["next_node"] == "pb"
    assert job["defer_seconds"] == 60

    row = (
        await db_session.execute(
            text("SELECT status, current_node_id FROM workflow_executions WHERE id = :i"),
            {"i": exec_id},
        )
    ).one()
    assert row.status == "paused"
    assert row.current_node_id == "pb"


@pytest.mark.asyncio
async def test_resume_after_delay_continues(
    db_session,
    seed_tenant_factory,
    insert_workflow,
    stub_step_enqueue,
) -> None:
    seed = await seed_tenant_factory()
    defn = {
        "nodes": [
            {"id": "trigger_1", "type": "trigger"},
            {"id": "d", "type": "delay", "config": {"seconds": 60}},
            {"id": "pb", "type": "pause_bot"},
        ],
        "edges": [
            {"from": "trigger_1", "to": "d"},
            {"from": "d", "to": "pb"},
        ],
    }
    _, exec_id = await insert_workflow(
        tenant_id=seed["tenant_id"],
        conversation_id=seed["conversation_id"],
        definition=defn,
    )

    await execute_workflow(db_session, exec_id)
    await db_session.commit()
    # Simulate the arq step-job firing.
    await execute_workflow(db_session, exec_id, start_node_id="pb")
    await db_session.commit()

    paused = (
        await db_session.execute(
            text("SELECT bot_paused FROM conversation_state WHERE conversation_id = :c"),
            {"c": seed["conversation_id"]},
        )
    ).scalar()
    status = (
        await db_session.execute(
            text("SELECT status FROM workflow_executions WHERE id = :i"),
            {"i": exec_id},
        )
    ).scalar()
    assert paused is True
    assert status == "completed"
