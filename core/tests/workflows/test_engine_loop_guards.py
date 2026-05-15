"""Loop and self-trigger guards.

Two distinct guards live in the engine:

- ``evaluate_event`` short-circuits when an event was produced by the same
  workflow's own execution (``source_workflow_execution_id``).
- ``execute_workflow`` enforces ``MAX_STEPS`` against the persisted
  ``steps_completed`` so a chain of delays cannot reset the counter.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import text

from atendia.workflows.engine import (
    MAX_STEPS,
    definition_for_steps,
    evaluate_event,
    execute_workflow,
)


@pytest.mark.asyncio
async def test_self_loop_event_is_skipped(
    db_session,
    seed_tenant_factory,
    insert_workflow,
) -> None:
    seed = await seed_tenant_factory()
    defn = definition_for_steps(
        "field_extracted",
        [{"type": "update_field", "config": {"field": "loop", "value": "x"}}],
    )
    _wf_id, exec_id = await insert_workflow(
        tenant_id=seed["tenant_id"],
        conversation_id=seed["conversation_id"],
        definition=defn,
        trigger_type="field_extracted",
    )

    # Insert an event tagged as produced by THIS workflow's execution.
    event_id = uuid4()
    await db_session.execute(
        text(
            "INSERT INTO events "
            "(id, conversation_id, tenant_id, type, payload, occurred_at, "
            " source_workflow_execution_id) "
            "VALUES (:id, :c, :t, 'field_extracted', :p, :o, :src)"
        ),
        {
            "id": event_id,
            "c": seed["conversation_id"],
            "t": seed["tenant_id"],
            "p": '{"field":"loop"}',
            "o": datetime.now(UTC),
            "src": exec_id,
        },
    )
    await db_session.commit()

    started = await evaluate_event(db_session, event_id)
    assert started == [], "self-loop event should not start a new execution"


@pytest.mark.asyncio
async def test_external_event_does_trigger_workflow(
    db_session,
    seed_tenant_factory,
    insert_workflow,
) -> None:
    seed = await seed_tenant_factory()
    defn = definition_for_steps(
        "field_extracted",
        [{"type": "update_field", "config": {"field": "loop", "value": "x"}}],
    )
    await insert_workflow(
        tenant_id=seed["tenant_id"],
        conversation_id=seed["conversation_id"],
        definition=defn,
        trigger_type="field_extracted",
    )

    event_id = uuid4()
    await db_session.execute(
        text(
            "INSERT INTO events "
            "(id, conversation_id, tenant_id, type, payload, occurred_at) "
            "VALUES (:id, :c, :t, 'field_extracted', :p, :o)"
        ),
        {
            "id": event_id,
            "c": seed["conversation_id"],
            "t": seed["tenant_id"],
            "p": '{"field":"loop"}',
            "o": datetime.now(UTC),
        },
    )
    await db_session.commit()

    started = await evaluate_event(db_session, event_id)
    await db_session.commit()
    assert len(started) == 1


@pytest.mark.asyncio
async def test_max_steps_persists_across_resume(
    db_session,
    seed_tenant_factory,
    insert_workflow,
    stub_step_enqueue,
) -> None:
    """A workflow whose steps_completed is already at the cap should fail
    on the next resume — proving that the counter survives delay/resume."""
    seed = await seed_tenant_factory()
    defn = definition_for_steps("message_received", [{"type": "pause_bot"}])
    _, exec_id = await insert_workflow(
        tenant_id=seed["tenant_id"],
        conversation_id=seed["conversation_id"],
        definition=defn,
    )
    # Simulate that a previous run already burned all steps.
    await db_session.execute(
        text(
            "UPDATE workflow_executions SET steps_completed = :n, status = 'paused' WHERE id = :i"
        ),
        {"i": exec_id, "n": MAX_STEPS},
    )
    await db_session.commit()

    await execute_workflow(db_session, exec_id, start_node_id="action_1")
    await db_session.commit()

    row = (
        await db_session.execute(
            text("SELECT status, error_code FROM workflow_executions WHERE id = :i"),
            {"i": exec_id},
        )
    ).one()
    assert row.status == "failed"
    assert row.error_code == "MAX_STEPS_EXCEEDED"
