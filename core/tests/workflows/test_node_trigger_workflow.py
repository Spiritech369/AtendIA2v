"""W6 — _node_trigger_workflow creates a child execution, sets the
parent_execution_id, refuses recursion, and continues fire-and-forget."""

from __future__ import annotations

import asyncio
import json
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from atendia.config import get_settings


def _wf_def(*, trigger_node_target: str | None = None) -> str:
    """Return a JSONB-encoded definition string for INSERT."""
    if trigger_node_target:
        d = {
            "nodes": [
                {
                    "id": "trig",
                    "type": "trigger_workflow",
                    "config": {"target_workflow_id": trigger_node_target},
                },
                {"id": "end", "type": "end", "config": {}},
            ],
            "edges": [{"from": "trig", "to": "end"}],
        }
    else:
        d = {
            "nodes": [{"id": "n1", "type": "end", "config": {}}],
            "edges": [],
        }
    return json.dumps(d)


@pytest.fixture
def two_workflows() -> tuple[str, str, str]:
    """Tenant + 2 workflows (parent + child). Yields
    (tenant_id, parent_workflow_id, child_workflow_id)."""

    async def _seed() -> tuple[str, str, str]:
        e = create_async_engine(get_settings().database_url)
        try:
            async with e.begin() as conn:
                tid = (
                    await conn.execute(
                        text("INSERT INTO tenants (name) VALUES (:n) RETURNING id"),
                        {"n": f"w6_trigger_{uuid4().hex[:8]}"},
                    )
                ).scalar()
                child_wid = (
                    await conn.execute(
                        text(
                            "INSERT INTO workflows "
                            "(tenant_id, name, trigger_type, trigger_config, "
                            " definition, active) "
                            "VALUES (:t, 'child', 'message_received', CAST('{}' AS jsonb), "
                            "        CAST(:d AS jsonb), true) "
                            "RETURNING id"
                        ),
                        {"t": tid, "d": _wf_def()},
                    )
                ).scalar()
                parent_wid = (
                    await conn.execute(
                        text(
                            "INSERT INTO workflows "
                            "(tenant_id, name, trigger_type, trigger_config, "
                            " definition, active) "
                            "VALUES (:t, 'parent', 'message_received', CAST('{}' AS jsonb), "
                            "        CAST(:d AS jsonb), true) "
                            "RETURNING id"
                        ),
                        {"t": tid, "d": _wf_def(trigger_node_target=str(child_wid))},
                    )
                ).scalar()
            return str(tid), str(parent_wid), str(child_wid)
        finally:
            await e.dispose()

    async def _cleanup(tid: str) -> None:
        e = create_async_engine(get_settings().database_url)
        try:
            async with e.begin() as conn:
                await conn.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": tid})
        finally:
            await e.dispose()

    tid, parent, child = asyncio.run(_seed())
    yield tid, parent, child
    asyncio.run(_cleanup(tid))


async def test_trigger_workflow_creates_child_execution(two_workflows):
    """Happy path: trigger_workflow node creates a child execution
    with parent_execution_id set and status 'running'."""
    from atendia.db.models.workflow import Workflow, WorkflowExecution
    from atendia.workflows.engine import _node_trigger_workflow

    _, parent_wid, child_wid = two_workflows
    sm = async_sessionmaker(
        create_async_engine(get_settings().database_url), expire_on_commit=False
    )
    async with sm() as session:
        parent_wf = (
            await session.execute(select(Workflow).where(Workflow.id == parent_wid))
        ).scalar_one()
        parent_exec = WorkflowExecution(workflow_id=parent_wf.id, status="running")
        session.add(parent_exec)
        await session.flush()

        node = {
            "id": "trig",
            "type": "trigger_workflow",
            "config": {"target_workflow_id": child_wid},
        }
        await _node_trigger_workflow(
            session,
            parent_wf,
            parent_exec,
            node,
            node["config"],
        )
        await session.commit()

        children = (
            (
                await session.execute(
                    select(WorkflowExecution).where(
                        WorkflowExecution.parent_execution_id == parent_exec.id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(children) == 1
        assert str(children[0].workflow_id) == child_wid
        assert children[0].status == "running"


async def test_trigger_workflow_rejects_missing_target(two_workflows):
    from atendia.db.models.workflow import Workflow, WorkflowExecution
    from atendia.workflows.engine import _ExecutionFailure, _node_trigger_workflow

    _, parent_wid, _ = two_workflows
    sm = async_sessionmaker(
        create_async_engine(get_settings().database_url), expire_on_commit=False
    )
    async with sm() as session:
        parent_wf = (
            await session.execute(select(Workflow).where(Workflow.id == parent_wid))
        ).scalar_one()
        parent_exec = WorkflowExecution(workflow_id=parent_wf.id, status="running")
        session.add(parent_exec)
        await session.flush()
        node = {"id": "trig", "type": "trigger_workflow", "config": {}}
        with pytest.raises(_ExecutionFailure) as exc:
            await _node_trigger_workflow(
                session,
                parent_wf,
                parent_exec,
                node,
                node["config"],
            )
        assert exc.value.code == "MISSING_TARGET_WORKFLOW"


async def test_trigger_workflow_rejects_self_recursion(two_workflows):
    """A workflow that tries to trigger itself → WORKFLOW_RECURSION."""
    from atendia.db.models.workflow import Workflow, WorkflowExecution
    from atendia.workflows.engine import _ExecutionFailure, _node_trigger_workflow

    _, parent_wid, _ = two_workflows
    sm = async_sessionmaker(
        create_async_engine(get_settings().database_url), expire_on_commit=False
    )
    async with sm() as session:
        parent_wf = (
            await session.execute(select(Workflow).where(Workflow.id == parent_wid))
        ).scalar_one()
        parent_exec = WorkflowExecution(workflow_id=parent_wf.id, status="running")
        session.add(parent_exec)
        await session.flush()
        node = {
            "id": "trig",
            "type": "trigger_workflow",
            "config": {"target_workflow_id": parent_wid},
        }  # SELF
        with pytest.raises(_ExecutionFailure) as exc:
            await _node_trigger_workflow(
                session,
                parent_wf,
                parent_exec,
                node,
                node["config"],
            )
        assert exc.value.code == "WORKFLOW_RECURSION"


async def test_trigger_workflow_rejects_other_tenant(two_workflows):
    """Target workflow that belongs to a different tenant →
    TARGET_WORKFLOW_NOT_FOUND."""
    from atendia.db.models.workflow import Workflow, WorkflowExecution
    from atendia.workflows.engine import _ExecutionFailure, _node_trigger_workflow

    _, parent_wid, _ = two_workflows

    async def _seed_other() -> str:
        e = create_async_engine(get_settings().database_url)
        try:
            async with e.begin() as conn:
                other_tid = (
                    await conn.execute(
                        text("INSERT INTO tenants (name) VALUES (:n) RETURNING id"),
                        {"n": f"w6_other_{uuid4().hex[:8]}"},
                    )
                ).scalar()
                wid = (
                    await conn.execute(
                        text(
                            "INSERT INTO workflows "
                            "(tenant_id, name, trigger_type, trigger_config, "
                            " definition, active) "
                            "VALUES (:t, 'foreign', 'message_received', "
                            "        CAST('{}' AS jsonb), CAST('{}' AS jsonb), true) "
                            "RETURNING id"
                        ),
                        {"t": other_tid},
                    )
                ).scalar()
            return str(wid)
        finally:
            await e.dispose()

    foreign_wid = await _seed_other()
    sm = async_sessionmaker(
        create_async_engine(get_settings().database_url), expire_on_commit=False
    )
    try:
        async with sm() as session:
            parent_wf = (
                await session.execute(select(Workflow).where(Workflow.id == parent_wid))
            ).scalar_one()
            parent_exec = WorkflowExecution(workflow_id=parent_wf.id, status="running")
            session.add(parent_exec)
            await session.flush()
            node = {
                "id": "trig",
                "type": "trigger_workflow",
                "config": {"target_workflow_id": foreign_wid},
            }
            with pytest.raises(_ExecutionFailure) as exc:
                await _node_trigger_workflow(
                    session,
                    parent_wf,
                    parent_exec,
                    node,
                    node["config"],
                )
            assert exc.value.code == "TARGET_WORKFLOW_NOT_FOUND"
    finally:

        async def _cleanup() -> None:
            e = create_async_engine(get_settings().database_url)
            try:
                async with e.begin() as conn:
                    await conn.execute(text("DELETE FROM tenants WHERE name LIKE 'w6_other_%'"))
            finally:
                await e.dispose()

        await _cleanup()
