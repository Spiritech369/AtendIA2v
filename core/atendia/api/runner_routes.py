from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.config import get_settings
from atendia.contracts.message import Message, MessageDirection
from atendia.db.session import get_db_session
from atendia.runner.conversation_runner import ConversationRunner
from atendia.runner.nlu_canned import CannedNLU
from atendia.runner.provider_factory import build_composer

router = APIRouter()


class RunTurnRequest(BaseModel):
    conversation_id: UUID
    tenant_id: UUID
    text: str
    turn_number: int
    fixture_path: str


class RunTurnResponse(BaseModel):
    turn_trace_id: UUID
    next_stage: str
    stage_transition: str | None


@router.post("/runner/turn", response_model=RunTurnResponse)
async def run_turn(
    req: RunTurnRequest,
    session: AsyncSession = Depends(get_db_session),
) -> RunTurnResponse:
    fp = Path(req.fixture_path)
    if not fp.exists():
        raise HTTPException(status_code=404, detail=f"fixture not found: {fp}")

    try:
        composer = build_composer(get_settings())
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    runner = ConversationRunner(session, CannedNLU(fp), composer)
    inbound = Message(
        id=str(uuid4()),
        conversation_id=str(req.conversation_id),
        tenant_id=str(req.tenant_id),
        direction=MessageDirection.INBOUND,
        text=req.text,
        sent_at=datetime.now(UTC),
    )
    trace = await runner.run_turn(
        conversation_id=req.conversation_id,
        tenant_id=req.tenant_id,
        inbound=inbound,
        turn_number=req.turn_number,
    )
    await session.commit()
    return RunTurnResponse(
        turn_trace_id=trace.id,
        next_stage=trace.state_after["current_stage"],
        stage_transition=trace.stage_transition,
    )
