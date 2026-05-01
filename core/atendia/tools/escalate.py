from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.db.models import HumanHandoff
from atendia.tools.base import Tool


class EscalateToHumanInput(BaseModel):
    tenant_id: UUID
    conversation_id: UUID
    reason: str


class EscalateToHumanTool(Tool):
    name = "escalate_to_human"

    async def run(self, session: AsyncSession, **kwargs: Any) -> dict:
        params = EscalateToHumanInput.model_validate(kwargs)
        row = HumanHandoff(
            id=uuid4(),
            tenant_id=params.tenant_id,
            conversation_id=params.conversation_id,
            reason=params.reason,
            status="open",
        )
        session.add(row)
        await session.flush()
        return {
            "handoff_id": str(row.id),
            "status": row.status,
        }
