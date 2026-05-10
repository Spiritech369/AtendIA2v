from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.channels.base import OutboundMessage
from atendia.db.models.outbound_outbox import OutboundOutbox


async def stage_outbound(session: AsyncSession, msg: OutboundMessage) -> UUID:
    """Persist an outbound send request inside the caller's DB transaction."""
    stmt = (
        pg_insert(OutboundOutbox)
        .values(
            tenant_id=UUID(msg.tenant_id),
            idempotency_key=msg.idempotency_key,
            payload=msg.model_dump(mode="json"),
            status="pending",
            available_at=datetime.now(UTC),
        )
        .on_conflict_do_nothing(index_elements=["idempotency_key"])
        .returning(OutboundOutbox.id)
    )
    outbox_id = (await session.execute(stmt)).scalar_one_or_none()
    if outbox_id is not None:
        return outbox_id
    return (
        await session.execute(
            select(OutboundOutbox.id).where(
                OutboundOutbox.idempotency_key == msg.idempotency_key,
            )
        )
    ).scalar_one()


async def get_or_stage_outbound(session: AsyncSession, msg: OutboundMessage) -> OutboundOutbox:
    await stage_outbound(session, msg)
    return (
        await session.execute(
            select(OutboundOutbox).where(
                OutboundOutbox.idempotency_key == msg.idempotency_key,
            )
        )
    ).scalar_one()
