from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from atendia.conversation_control.conversation_status import ConversationControlResult
from atendia.decision_engine.blocked_actions import normalized_blocked_actions
from atendia.operational_intent.risk_policy import OperationalIntentResult


class DecisionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    next_action: str
    allowed: bool
    blocked_actions: list[str] = Field(default_factory=list)
    must_answer_first: str | None = None
    pending_to_resume: dict[str, object] | None = None
    handoff_required: bool = False
    composer_allowed: bool = True
    pipeline_blocked: bool = False
    outbound_blocked_reason: str | None = None


def build_control_decision(
    *,
    control: ConversationControlResult,
    intent: OperationalIntentResult,
) -> DecisionResult:
    blocked_actions = normalized_blocked_actions(intent.blocked_actions)
    if not control.bot_allowed:
        return DecisionResult(
            next_action="handoff" if control.handoff_required or intent.effects.handoff_required else "blocked",
            allowed=True,
            blocked_actions=blocked_actions,
            handoff_required=control.handoff_required or intent.effects.handoff_required,
            composer_allowed=False,
            pipeline_blocked=True,
            outbound_blocked_reason=control.pause_reason or "bot_not_allowed",
        )
    if intent.effects.block_pipeline:
        safe_reply = (
            control.bot_allowed
            and intent.auto_reply_allowed
            and bool(intent.response_template)
            and not intent.effects.handoff_required
        )
        return DecisionResult(
            next_action=(
                "handoff"
                if intent.effects.handoff_required
                else "safe_reply"
                if safe_reply
                else "blocked"
            ),
            allowed=True,
            blocked_actions=blocked_actions,
            handoff_required=intent.effects.handoff_required,
            composer_allowed=False,
            pipeline_blocked=True,
            outbound_blocked_reason=None if safe_reply else "pipeline_blocked",
        )
    return DecisionResult(
        next_action="continue",
        allowed=True,
        blocked_actions=blocked_actions,
        handoff_required=intent.effects.handoff_required,
        composer_allowed=True,
        pipeline_blocked=False,
        outbound_blocked_reason=None,
    )


__all__ = ["DecisionResult", "build_control_decision"]
