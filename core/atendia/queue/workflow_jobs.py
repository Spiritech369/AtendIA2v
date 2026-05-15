from __future__ import annotations

from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from atendia.config import get_settings
from atendia.db.models.event import EventRow
from atendia.db.models.workflow import WorkflowEventCursor
from atendia.workflows.engine import evaluate_event, execute_workflow


async def execute_workflow_step(
    ctx: dict,
    execution_id: str,
    start_node_id: str | None = None,
) -> dict:
    """Resume (or start) a workflow execution.

    Enqueued by the engine's delay handler with a deterministic
    ``_job_id`` and to the dedicated ``workflows`` queue. Caller passes
    ``start_node_id=None`` for fresh executions.
    """
    settings = get_settings()
    engine = ctx.get("engine") or create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            await execute_workflow(session, UUID(execution_id), start_node_id=start_node_id)
            await session.commit()
    finally:
        if "engine" not in ctx:
            await engine.dispose()
    return {"status": "ok", "execution_id": execution_id}


async def poll_workflow_triggers(ctx: dict) -> dict:
    """Cron backup path: replay any events the inline runner-hook missed.

    The hot-path inline trigger from ``ConversationRunner`` is not yet wired,
    so today this cron *is* the only trigger path. It runs executions inline
    (we're already in worker context). When the runner hook lands, this
    becomes a backstop for missed/late events only.
    """
    settings = get_settings()
    engine = ctx.get("engine") or create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    processed = 0
    try:
        async with session_factory() as session:
            tenants = (await session.execute(select(EventRow.tenant_id).distinct())).scalars().all()
            for tenant_id in tenants:
                cursor = (
                    await session.execute(
                        select(WorkflowEventCursor).where(
                            WorkflowEventCursor.tenant_id == tenant_id,
                        )
                    )
                ).scalar_one_or_none()
                last_created_at = cursor.last_created_at if cursor else None
                last_event_id = cursor.last_event_id if cursor else None
                if cursor and last_created_at is None and last_event_id:
                    last_created_at = (
                        await session.execute(
                            select(EventRow.created_at).where(
                                EventRow.id == last_event_id,
                            )
                        )
                    ).scalar_one_or_none()
                stmt = (
                    select(EventRow)
                    .where(EventRow.tenant_id == tenant_id)
                    .order_by(EventRow.created_at.asc(), EventRow.id.asc())
                    .limit(100)
                )
                if last_created_at is not None and last_event_id is not None:
                    stmt = stmt.where(
                        or_(
                            EventRow.created_at > last_created_at,
                            and_(
                                EventRow.created_at == last_created_at,
                                EventRow.id > last_event_id,
                            ),
                        )
                    )
                elif last_created_at is not None:
                    stmt = stmt.where(EventRow.created_at > last_created_at)
                events = (await session.execute(stmt)).scalars().all()
                for event in events:
                    started = await evaluate_event(session, event.id)
                    for execution_id in started:
                        await execute_workflow(session, execution_id)
                    if cursor is None:
                        cursor = WorkflowEventCursor(tenant_id=tenant_id)
                        session.add(cursor)
                    cursor.last_event_id = event.id
                    cursor.last_created_at = event.created_at
                    processed += 1
            await session.commit()
    finally:
        if "engine" not in ctx:
            await engine.dispose()
    return {"processed": processed}
