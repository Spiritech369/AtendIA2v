"""W6 — recursion guard for trigger_workflow node.

Walks parent_execution_id chain. Returns True if the target workflow
id appears anywhere in the chain (or matches the immediate parent).
Capped at depth 5 to prevent infinite loops from corrupt data."""

from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from atendia.config import get_settings


@pytest.fixture
def workflow_chain() -> tuple[str, list[str]]:
    """Insert a tenant + 3 workflows + a linear execution chain
    (root → middle → leaf) all sharing tenant. Yields
    (tenant_id, [wf_root, wf_middle, wf_leaf, exec_root, exec_middle, exec_leaf]).
    Cleaned up after."""

    async def _seed() -> tuple[str, list[str]]:
        e = create_async_engine(get_settings().database_url)
        try:
            async with e.begin() as conn:
                tid = (
                    await conn.execute(
                        text("INSERT INTO tenants (name) VALUES (:n) RETURNING id"),
                        {"n": f"w6_recursion_{uuid4().hex[:8]}"},
                    )
                ).scalar()
                wf_ids = []
                for label in ("root", "middle", "leaf"):
                    wid = (
                        await conn.execute(
                            text(
                                "INSERT INTO workflows "
                                "(tenant_id, name, trigger_type, definition, active) "
                                "VALUES (:t, :n, 'message_received', "
                                'CAST(\'{"nodes":[],"edges":[]}\' AS jsonb), true) '
                                "RETURNING id"
                            ),
                            {"t": tid, "n": f"wf_{label}_{uuid4().hex[:6]}"},
                        )
                    ).scalar()
                    wf_ids.append(str(wid))
                exec_ids = []
                prev = None
                for wid in wf_ids:
                    eid = (
                        await conn.execute(
                            text(
                                "INSERT INTO workflow_executions "
                                "(workflow_id, status, parent_execution_id) "
                                "VALUES (:w, 'running', :p) RETURNING id"
                            ),
                            {"w": wid, "p": prev},
                        )
                    ).scalar()
                    exec_ids.append(str(eid))
                    prev = eid
            return str(tid), wf_ids + exec_ids
        finally:
            await e.dispose()

    async def _cleanup(tid: str) -> None:
        e = create_async_engine(get_settings().database_url)
        try:
            async with e.begin() as conn:
                await conn.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": tid})
        finally:
            await e.dispose()

    tid, ids = asyncio.run(_seed())
    yield tid, ids
    asyncio.run(_cleanup(tid))


async def test_detects_recursion_when_target_is_self(workflow_chain):
    """If a workflow tries to trigger itself, the guard fires
    immediately — without walking the parent chain at all."""
    from atendia.db.models.workflow import WorkflowExecution
    from atendia.workflows.engine import _detects_workflow_recursion

    _, ids = workflow_chain
    wf_root, _, _, exec_root, _, _ = ids
    sm = async_sessionmaker(
        create_async_engine(get_settings().database_url), expire_on_commit=False
    )
    async with sm() as session:
        execution = (
            await session.execute(
                select(WorkflowExecution).where(WorkflowExecution.id == exec_root)
            )
        ).scalar_one()
        assert await _detects_workflow_recursion(session, execution, UUID(wf_root)) is True


async def test_detects_recursion_in_ancestor(workflow_chain):
    """leaf execution tries to trigger workflow_root — root is an
    ancestor of leaf, so the guard fires."""
    from atendia.db.models.workflow import WorkflowExecution
    from atendia.workflows.engine import _detects_workflow_recursion

    _, ids = workflow_chain
    wf_root, _, _, _, _, exec_leaf = ids
    sm = async_sessionmaker(
        create_async_engine(get_settings().database_url), expire_on_commit=False
    )
    async with sm() as session:
        leaf_exec = (
            await session.execute(
                select(WorkflowExecution).where(WorkflowExecution.id == exec_leaf)
            )
        ).scalar_one()
        assert await _detects_workflow_recursion(session, leaf_exec, UUID(wf_root)) is True


async def test_no_recursion_for_unrelated_target(workflow_chain):
    """leaf execution triggers a completely different workflow not
    in its parent chain — no recursion."""
    from atendia.db.models.workflow import WorkflowExecution
    from atendia.workflows.engine import _detects_workflow_recursion

    _, ids = workflow_chain
    _, _, _, _, _, exec_leaf = ids
    sm = async_sessionmaker(
        create_async_engine(get_settings().database_url), expire_on_commit=False
    )
    async with sm() as session:
        leaf_exec = (
            await session.execute(
                select(WorkflowExecution).where(WorkflowExecution.id == exec_leaf)
            )
        ).scalar_one()
        unrelated = uuid4()
        assert await _detects_workflow_recursion(session, leaf_exec, unrelated) is False
