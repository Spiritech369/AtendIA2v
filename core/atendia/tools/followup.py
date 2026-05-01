from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.db.models import FollowupScheduled
from atendia.tools.base import Tool


class ScheduleFollowupInput(BaseModel):
    tenant_id: UUID
    conversation_id: UUID
    when: datetime
    template_id: UUID | None = None


class ScheduleFollowupTool(Tool):
    name = "schedule_followup"

    async def run(self, session: AsyncSession, **kwargs: Any) -> dict:
        params = ScheduleFollowupInput.model_validate(kwargs)
        row = FollowupScheduled(
            id=uuid4(),
            tenant_id=params.tenant_id,
            conversation_id=params.conversation_id,
            run_at=params.when,
            template_id=params.template_id,
            status="pending",
            attempts=0,
        )
        session.add(row)
        await session.flush()
        return {
            "followup_id": str(row.id),
            "status": row.status,
            "run_at": params.when.isoformat(),
        }
