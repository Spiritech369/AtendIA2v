from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.db.models.conversation import Conversation, ConversationStateRow
from atendia.db.models.lifecycle import LifecycleStageHistory
from atendia.lifecycle.adapter import PipelineLifecycleAdapter
from atendia.lifecycle.schemas import LifecycleDecision, LifecycleStageUpdateRequest


class LifecycleService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        adapter: PipelineLifecycleAdapter | None = None,
    ) -> None:
        self._session = session
        self._adapter = adapter or PipelineLifecycleAdapter(session)

    async def get_current_stage(
        self,
        *,
        tenant_id: UUID,
        conversation_id: UUID,
    ) -> str | None:
        return (
            await self._session.execute(
                select(Conversation.current_stage).where(
                    Conversation.id == conversation_id,
                    Conversation.tenant_id == tenant_id,
                    Conversation.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()

    async def suggest_stage_update(
        self,
        request: LifecycleStageUpdateRequest,
    ) -> LifecycleDecision:
        return await self.validate_stage_update(request)

    async def validate_stage_update(
        self,
        request: LifecycleStageUpdateRequest,
    ) -> LifecycleDecision:
        current = await self.get_current_stage(
            tenant_id=request.tenant_id,
            conversation_id=request.conversation_id,
        )
        if current is None:
            return LifecycleDecision(
                conversation_id=request.conversation_id,
                to_stage=request.target_stage,
                valid=False,
                reason="conversation not found for tenant",
                evidence=list(request.evidence),
                confidence=request.confidence,
            )
        if not request.reason.strip():
            return LifecycleDecision(
                conversation_id=request.conversation_id,
                from_stage=current,
                to_stage=request.target_stage,
                valid=False,
                reason="lifecycle update requires reason",
                evidence=list(request.evidence),
                confidence=request.confidence,
            )
        if not request.evidence:
            return LifecycleDecision(
                conversation_id=request.conversation_id,
                from_stage=current,
                to_stage=request.target_stage,
                valid=False,
                reason="lifecycle update requires evidence",
                evidence=[],
                confidence=request.confidence,
            )
        valid, reason, metadata = await self._adapter.validate_stage_change(
            tenant_id=request.tenant_id,
            from_stage=current,
            to_stage=request.target_stage,
        )
        return LifecycleDecision(
            conversation_id=request.conversation_id,
            from_stage=current,
            to_stage=request.target_stage,
            valid=valid,
            reason=reason,
            evidence=list(request.evidence),
            confidence=request.confidence,
            metadata=metadata,
        )

    async def apply_stage_update(
        self,
        request: LifecycleStageUpdateRequest,
    ) -> LifecycleDecision:
        decision = await self.validate_stage_update(request)
        if not decision.valid:
            return decision
        if decision.from_stage == request.target_stage:
            history = await self.record_stage_history(request, from_stage=decision.from_stage)
            return decision.model_copy(
                update={
                    "applied": False,
                    "history_id": history.id,
                    "reason": "already in target lifecycle stage",
                }
            )

        now = datetime.now(UTC)
        await self._session.execute(
            update(Conversation)
            .where(
                Conversation.id == request.conversation_id,
                Conversation.tenant_id == request.tenant_id,
                Conversation.deleted_at.is_(None),
            )
            .values(current_stage=request.target_stage, last_activity_at=now)
        )
        await self._session.execute(
            update(ConversationStateRow)
            .where(ConversationStateRow.conversation_id == request.conversation_id)
            .values(stage_entered_at=now)
        )
        history = await self.record_stage_history(request, from_stage=decision.from_stage)
        return decision.model_copy(update={"applied": True, "history_id": history.id})

    async def record_stage_history(
        self,
        request: LifecycleStageUpdateRequest,
        *,
        from_stage: str | None,
    ) -> LifecycleStageHistory:
        row = LifecycleStageHistory(
            tenant_id=request.tenant_id,
            conversation_id=request.conversation_id,
            from_stage=from_stage,
            to_stage=request.target_stage,
            reason=request.reason,
            evidence=list(request.evidence),
            confidence=request.confidence,
            source=request.source,
            trace_id=request.trace_id,
            created_by=request.created_by,
            metadata_json=dict(request.metadata),
        )
        self._session.add(row)
        await self._session.flush()
        return row
