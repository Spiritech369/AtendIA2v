from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from atendia.contracts.event import EventType
from atendia.db.models import EventRow


class EventEmitter:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def emit(
        self,
        *,
        conversation_id: UUID | None,
        tenant_id: UUID,
        event_type: EventType,
        payload: dict,
        trace_id: str | None = None,
    ) -> EventRow:
        row = EventRow(
            id=uuid4(),
            conversation_id=conversation_id,
            tenant_id=tenant_id,
            type=event_type.value,
            payload=payload,
            occurred_at=datetime.now(timezone.utc),
            trace_id=trace_id,
        )
        self._session.add(row)
        await self._session.flush()
        return row
