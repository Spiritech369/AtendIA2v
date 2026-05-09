"""Shared fixtures for ``tests/workflows/*``.

These tests exercise the engine against a real Postgres so the SQL queries,
foreign keys, and unique-index idempotency all hold under the same conditions
as production. Redis side-effects (``send_outbound`` enqueue, delay resume)
are stubbed via monkeypatch — they're tested independently in ``tests/queue``.

Both fixtures (``db_session`` for ORM access, ``seed_tenant_factory`` for raw
inserts) yield async objects so the test body never has to spin up its own
event loop alongside pytest-asyncio's.
"""
from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from atendia.config import get_settings
from atendia.workflows import engine as engine_mod


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(get_settings().database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        yield session
        await session.rollback()
    await engine.dispose()


@pytest.fixture
def stub_outbound_enqueue(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """Replace the engine's outbound enqueue with a recorder. Tests assert
    against the captured ``OutboundMessage`` instances.
    """
    captured: list[Any] = []

    async def _capture(msg: Any) -> str:
        captured.append(msg)
        return msg.idempotency_key

    monkeypatch.setattr(engine_mod, "_enqueue_outbound_for_workflow", _capture)
    return captured


@pytest.fixture
def stub_step_enqueue(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    """Replace the engine's delay-resume enqueue with a recorder."""
    captured: list[dict] = []

    async def _capture(
        execution_id: UUID,
        next_node: str | None,
        *,
        defer_seconds: int,
        node_id: str,
    ) -> None:
        captured.append({
            "execution_id": execution_id,
            "next_node": next_node,
            "defer_seconds": defer_seconds,
            "node_id": node_id,
        })

    monkeypatch.setattr(engine_mod, "_enqueue_workflow_step", _capture)
    return captured


@pytest_asyncio.fixture
async def seed_tenant_factory() -> AsyncIterator[Callable[..., Awaitable[dict]]]:
    """Async helper to seed (tenant, customer, conversation, state) +
    optional inbound message + optional pipeline + optional agent + user.

    Returns a coroutine that yields a dict with the inserted ids. Cleans
    up the seeded tenants once the test exits.
    """
    created_tids: list[str] = []

    async def _seed(
        *,
        with_recent_inbound: bool = True,
        pipeline_stages: list[str] | None = None,
        agent_count: int = 0,
        user_role: str | None = None,
    ) -> dict:
        async def _do() -> dict:
            engine = create_async_engine(get_settings().database_url)
            try:
                async with engine.begin() as conn:
                    tid = (
                        await conn.execute(
                            text("INSERT INTO tenants (name) VALUES (:n) RETURNING id"),
                            {"n": f"wf_test_{uuid4().hex[:10]}"},
                        )
                    ).scalar()
                    cust_id = (
                        await conn.execute(
                            text(
                                "INSERT INTO customers (tenant_id, phone_e164, name, score) "
                                "VALUES (:t, :p, 'Ana', 50) RETURNING id"
                            ),
                            {"t": tid, "p": f"+52155{uuid4().hex[:8]}"},
                        )
                    ).scalar()
                    conv_id = (
                        await conn.execute(
                            text(
                                "INSERT INTO conversations (tenant_id, customer_id, current_stage) "
                                "VALUES (:t, :c, 'lead') RETURNING id"
                            ),
                            {"t": tid, "c": cust_id},
                        )
                    ).scalar()
                    await conn.execute(
                        text(
                            "INSERT INTO conversation_state (conversation_id, extracted_data) "
                            "VALUES (:c, :d)"
                        ),
                        {"c": conv_id, "d": "{}"},
                    )
                    if with_recent_inbound:
                        await conn.execute(
                            text(
                                "INSERT INTO messages "
                                "(conversation_id, tenant_id, direction, text, sent_at) "
                                "VALUES (:c, :t, 'inbound', 'hola', now())"
                            ),
                            {"c": conv_id, "t": tid},
                        )
                    pipeline_id = None
                    if pipeline_stages is not None:
                        stage_objs = [
                            f'{{"id":"{sid}","label":"{sid}","timeout_hours":1}}'
                            for sid in pipeline_stages
                        ]
                        definition_json = (
                            '{"stages":[' + ",".join(stage_objs)
                            + '],"docs_per_plan":{"default":["docs_ine"]}}'
                        )
                        pipeline_id = (
                            await conn.execute(
                                text(
                                    "INSERT INTO tenant_pipelines "
                                    "(tenant_id, version, definition, active) "
                                    "VALUES (:t, 1, :d, true) RETURNING id"
                                ),
                                {"t": tid, "d": definition_json},
                            )
                        ).scalar()
                    agent_ids: list[str] = []
                    for i in range(agent_count):
                        agent_id = (
                            await conn.execute(
                                text(
                                    "INSERT INTO agents (tenant_id, name) "
                                    "VALUES (:t, :n) RETURNING id"
                                ),
                                {"t": tid, "n": f"agent_{i}"},
                            )
                        ).scalar()
                        agent_ids.append(str(agent_id))
                    user_id = None
                    if user_role is not None:
                        user_id = (
                            await conn.execute(
                                text(
                                    "INSERT INTO tenant_users (tenant_id, email, role) "
                                    "VALUES (:t, :e, :r) RETURNING id"
                                ),
                                {
                                    "t": tid,
                                    "e": f"u_{uuid4().hex[:6]}@example.com",
                                    "r": user_role,
                                },
                            )
                        ).scalar()
                return {
                    "tenant_id": str(tid),
                    "customer_id": str(cust_id),
                    "conversation_id": str(conv_id),
                    "pipeline_id": str(pipeline_id) if pipeline_id else None,
                    "agent_ids": agent_ids,
                    "user_id": str(user_id) if user_id else None,
                }
            finally:
                await engine.dispose()

        result = await _do()
        created_tids.append(result["tenant_id"])
        return result

    yield _seed

    engine = create_async_engine(get_settings().database_url)
    try:
        async with engine.begin() as conn:
            for tid in created_tids:
                await conn.execute(
                    text("DELETE FROM tenants WHERE id = :t"),
                    {"t": tid},
                )
    finally:
        await engine.dispose()


@pytest.fixture
def insert_workflow(db_session: AsyncSession):
    """Helper that inserts a Workflow + WorkflowExecution and returns ids.

    Tests that need a row to call ``execute_workflow`` against use this.
    """
    async def _do(
        *,
        tenant_id: str,
        conversation_id: str | None,
        definition: dict,
        trigger_type: str = "message_received",
        active: bool = True,
    ) -> tuple[UUID, UUID]:
        wf_id = uuid4()
        exec_id = uuid4()
        await db_session.execute(
            text(
                "INSERT INTO workflows "
                "(id, tenant_id, name, trigger_type, trigger_config, definition, active) "
                "VALUES (:id, :t, :n, :tt, '{}', :d, :a)"
            ),
            {
                "id": wf_id,
                "t": tenant_id,
                "n": f"wf_{wf_id.hex[:6]}",
                "tt": trigger_type,
                "d": __import__("json").dumps(definition),
                "a": active,
            },
        )
        await db_session.execute(
            text(
                "INSERT INTO workflow_executions (id, workflow_id, conversation_id, status) "
                "VALUES (:id, :w, :c, 'running')"
            ),
            {"id": exec_id, "w": wf_id, "c": conversation_id},
        )
        await db_session.commit()
        return wf_id, exec_id

    return _do
