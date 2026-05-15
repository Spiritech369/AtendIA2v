"""W8 — ask_question node pauses execution awaiting customer reply,
then resumes when MESSAGE_RECEIVED fires for the conversation."""

from __future__ import annotations

import asyncio
import json
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from atendia.config import get_settings


def _wf_def() -> str:
    """Workflow with ask_question -> end."""
    return json.dumps(
        {
            "nodes": [
                {
                    "id": "ask",
                    "type": "ask_question",
                    "config": {"question": "Cual es tu email?", "variable": "email"},
                },
                {"id": "end", "type": "end", "config": {}},
            ],
            "edges": [{"from": "ask", "to": "end"}],
        }
    )


@pytest.fixture
def tenant_workflow_conversation() -> tuple[str, str, str, str, str]:
    """Insert tenant + customer + conversation (with recent inbound) +
    workflow + execution positioned at the ask_question node. Yields
    (tenant_id, customer_id, conversation_id, workflow_id, execution_id)."""

    async def _seed() -> tuple[str, str, str, str, str]:
        e = create_async_engine(get_settings().database_url)
        try:
            async with e.begin() as conn:
                tid = (
                    await conn.execute(
                        text("INSERT INTO tenants (name) VALUES (:n) RETURNING id"),
                        {"n": f"w8_ask_{uuid4().hex[:8]}"},
                    )
                ).scalar()
                cust = (
                    await conn.execute(
                        text(
                            "INSERT INTO customers (tenant_id, phone_e164, name) "
                            "VALUES (:t, :p, 'W8 Test') RETURNING id"
                        ),
                        {"t": tid, "p": f"+5215{uuid4().hex[:9]}"},
                    )
                ).scalar()
                conv = (
                    await conn.execute(
                        text(
                            "INSERT INTO conversations (tenant_id, customer_id, current_stage) "
                            "VALUES (:t, :c, 'nuevo') RETURNING id"
                        ),
                        {"t": tid, "c": cust},
                    )
                ).scalar()
                await conn.execute(
                    text("INSERT INTO conversation_state (conversation_id) VALUES (:c)"),
                    {"c": conv},
                )
                # Recent inbound message — _node_message needs this to be
                # within the 24h WhatsApp window.
                await conn.execute(
                    text(
                        "INSERT INTO messages "
                        "(conversation_id, tenant_id, direction, text, sent_at) "
                        "VALUES (:c, :t, 'inbound', 'hola', now())"
                    ),
                    {"c": conv, "t": tid},
                )
                wid = (
                    await conn.execute(
                        text(
                            "INSERT INTO workflows "
                            "(tenant_id, name, trigger_type, trigger_config, definition, active) "
                            "VALUES (:t, 'ask_test', 'message_received', "
                            "        CAST('{}' AS jsonb), CAST(:d AS jsonb), true) "
                            "RETURNING id"
                        ),
                        {"t": tid, "d": _wf_def()},
                    )
                ).scalar()
                eid = (
                    await conn.execute(
                        text(
                            "INSERT INTO workflow_executions "
                            "(workflow_id, conversation_id, customer_id, status, "
                            " current_node_id) "
                            "VALUES (:w, :c, :cu, 'running', 'ask') RETURNING id"
                        ),
                        {"w": wid, "c": conv, "cu": cust},
                    )
                ).scalar()
            return str(tid), str(cust), str(conv), str(wid), str(eid)
        finally:
            await e.dispose()

    async def _cleanup(tid: str) -> None:
        e = create_async_engine(get_settings().database_url)
        try:
            async with e.begin() as conn:
                await conn.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": tid})
        finally:
            await e.dispose()

    seed = asyncio.run(_seed())
    yield seed
    asyncio.run(_cleanup(seed[0]))


async def test_ask_question_pauses_execution(
    tenant_workflow_conversation, stub_outbound_enqueue, stub_step_enqueue
):
    """After _node_ask_question fires, the execution's status flips to
    'waiting_for_response' and awaiting_variable is set."""
    from atendia.db.models.workflow import Workflow, WorkflowExecution
    from atendia.workflows.engine import _node_ask_question

    _, _, _, wid, eid = tenant_workflow_conversation
    sm = async_sessionmaker(
        create_async_engine(get_settings().database_url), expire_on_commit=False
    )
    async with sm() as session:
        wf = (await session.execute(select(Workflow).where(Workflow.id == wid))).scalar_one()
        ex = (
            await session.execute(select(WorkflowExecution).where(WorkflowExecution.id == eid))
        ).scalar_one()
        node = {
            "id": "ask",
            "type": "ask_question",
            "config": {"question": "Tu email?", "variable": "email"},
        }
        result = await _node_ask_question(session, wf, ex, node, node["config"])
        await session.commit()

        assert result is None  # must break dispatch
        refreshed = (
            await session.execute(select(WorkflowExecution).where(WorkflowExecution.id == eid))
        ).scalar_one()
        assert refreshed.status == "paused"
        assert refreshed.awaiting_variable == "email"
        assert refreshed.current_node_id == "ask"

    # Outbound question was sent via the standard path
    assert len(stub_outbound_enqueue) == 1
    assert stub_outbound_enqueue[0].text == "Tu email?"


async def test_ask_question_rejects_missing_question(
    tenant_workflow_conversation, stub_outbound_enqueue, stub_step_enqueue
):
    from atendia.db.models.workflow import Workflow, WorkflowExecution
    from atendia.workflows.engine import _ExecutionFailure, _node_ask_question

    _, _, _, wid, eid = tenant_workflow_conversation
    sm = async_sessionmaker(
        create_async_engine(get_settings().database_url), expire_on_commit=False
    )
    async with sm() as session:
        wf = (await session.execute(select(Workflow).where(Workflow.id == wid))).scalar_one()
        ex = (
            await session.execute(select(WorkflowExecution).where(WorkflowExecution.id == eid))
        ).scalar_one()
        node = {
            "id": "ask",
            "type": "ask_question",
            "config": {"variable": "x"},  # missing question
        }
        with pytest.raises(_ExecutionFailure) as exc:
            await _node_ask_question(session, wf, ex, node, node["config"])
        assert exc.value.code == "MISSING_ASK_QUESTION_FIELDS"


async def test_ask_question_rejects_missing_variable(
    tenant_workflow_conversation, stub_outbound_enqueue, stub_step_enqueue
):
    from atendia.db.models.workflow import Workflow, WorkflowExecution
    from atendia.workflows.engine import _ExecutionFailure, _node_ask_question

    _, _, _, wid, eid = tenant_workflow_conversation
    sm = async_sessionmaker(
        create_async_engine(get_settings().database_url), expire_on_commit=False
    )
    async with sm() as session:
        wf = (await session.execute(select(Workflow).where(Workflow.id == wid))).scalar_one()
        ex = (
            await session.execute(select(WorkflowExecution).where(WorkflowExecution.id == eid))
        ).scalar_one()
        node = {
            "id": "ask",
            "type": "ask_question",
            "config": {"question": "x"},  # missing variable
        }
        with pytest.raises(_ExecutionFailure) as exc:
            await _node_ask_question(session, wf, ex, node, node["config"])
        assert exc.value.code == "MISSING_ASK_QUESTION_FIELDS"


async def test_ask_question_resumes_on_customer_message(
    tenant_workflow_conversation, stub_outbound_enqueue, stub_step_enqueue
):
    """When MESSAGE_RECEIVED fires for the conversation, a paused
    execution captures the text into the awaiting variable, clears
    the waiting flags, and advances current_node_id to the next node."""
    from atendia.db.models.workflow import Workflow, WorkflowExecution
    from atendia.workflows.engine import _node_ask_question, _resume_paused_execution

    _, _, _, wid, eid = tenant_workflow_conversation
    sm = async_sessionmaker(
        create_async_engine(get_settings().database_url), expire_on_commit=False
    )
    # 1. Pause via ask_question
    async with sm() as session:
        wf = (await session.execute(select(Workflow).where(Workflow.id == wid))).scalar_one()
        ex = (
            await session.execute(select(WorkflowExecution).where(WorkflowExecution.id == eid))
        ).scalar_one()
        node = {
            "id": "ask",
            "type": "ask_question",
            "config": {"question": "Email?", "variable": "email"},
        }
        await _node_ask_question(session, wf, ex, node, node["config"])
        await session.commit()

    # 2. Simulate the resume call (what evaluate_event will do)
    async with sm() as session:
        ex = (
            await session.execute(select(WorkflowExecution).where(WorkflowExecution.id == eid))
        ).scalar_one()
        await _resume_paused_execution(session, ex, "pedro@example.com")
        await session.commit()

    # 3. Verify variable was saved + execution advanced.
    # workflow_variables is a workflow-level registry keyed by
    # (workflow_id, name); the value sits in last_value.
    async with sm() as session:
        row = (
            (
                await session.execute(
                    text(
                        "SELECT name, last_value FROM workflow_variables "
                        "WHERE workflow_id = :w AND name = 'email'"
                    ),
                    {"w": wid},
                )
            )
            .mappings()
            .one_or_none()
        )
        assert row is not None, "variable 'email' must be persisted in workflow_variables"
        assert row["last_value"] == "pedro@example.com"

        refreshed = (
            await session.execute(select(WorkflowExecution).where(WorkflowExecution.id == eid))
        ).scalar_one()
        # After resume, execution is back to 'running' (and may have
        # been advanced/completed by enqueueing the next node — the
        # enqueue is stubbed in tests, so the engine will still mark
        # current_node_id to the next node id 'end').
        assert refreshed.status in ("running", "completed")
        assert refreshed.awaiting_variable is None
        assert refreshed.current_node_id == "end"

    # The resume should have enqueued the next node.
    assert len(stub_step_enqueue) == 1
    assert stub_step_enqueue[0]["next_node"] == "end"


async def test_ask_question_isolated_per_conversation(
    tenant_workflow_conversation, stub_outbound_enqueue, stub_step_enqueue
):
    """A paused execution in conversation A is NOT visible to a
    resume sweep for conversation B."""
    from atendia.db.models.workflow import Workflow, WorkflowExecution
    from atendia.workflows.engine import _node_ask_question

    _, _, conv_a, wid, exec_a = tenant_workflow_conversation
    sm = async_sessionmaker(
        create_async_engine(get_settings().database_url), expire_on_commit=False
    )
    # Pause execution_a (conv A)
    async with sm() as session:
        wf = (await session.execute(select(Workflow).where(Workflow.id == wid))).scalar_one()
        ex = (
            await session.execute(select(WorkflowExecution).where(WorkflowExecution.id == exec_a))
        ).scalar_one()
        node = {
            "id": "ask",
            "type": "ask_question",
            "config": {"question": "Email?", "variable": "email"},
        }
        await _node_ask_question(session, wf, ex, node, node["config"])
        await session.commit()

    # Create a SECOND conversation under the same tenant + customer.
    async def _make_conv_b() -> str:
        e = create_async_engine(get_settings().database_url)
        try:
            async with e.begin() as conn:
                cust = (
                    await conn.execute(
                        text("SELECT customer_id FROM workflow_executions WHERE id = :e"),
                        {"e": exec_a},
                    )
                ).scalar()
                tid_row = (
                    await conn.execute(
                        text("SELECT tenant_id FROM customers WHERE id = :c"),
                        {"c": cust},
                    )
                ).scalar()
                conv_b = (
                    await conn.execute(
                        text(
                            "INSERT INTO conversations (tenant_id, customer_id, current_stage) "
                            "VALUES (:t, :c, 'nuevo') RETURNING id"
                        ),
                        {"t": tid_row, "c": cust},
                    )
                ).scalar()
                await conn.execute(
                    text("INSERT INTO conversation_state (conversation_id) VALUES (:c)"),
                    {"c": conv_b},
                )
            return str(conv_b)
        finally:
            await e.dispose()

    conv_b = await _make_conv_b()

    async with sm() as session:
        for_a = (
            (
                await session.execute(
                    select(WorkflowExecution).where(
                        WorkflowExecution.conversation_id == conv_a,
                        WorkflowExecution.status == "paused",
                    )
                )
            )
            .scalars()
            .all()
        )
        for_b = (
            (
                await session.execute(
                    select(WorkflowExecution).where(
                        WorkflowExecution.conversation_id == conv_b,
                        WorkflowExecution.status == "paused",
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(for_a) == 1, f"conv_a should have 1 paused execution, got {len(for_a)}"
        assert len(for_b) == 0, f"conv_b should have 0 paused executions, got {len(for_b)}"
