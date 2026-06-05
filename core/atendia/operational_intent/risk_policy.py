from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from atendia.operational_intent.policy_config import IntentCategory, RiskLevel


class OperationalEffects(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pause_bot: bool = False
    handoff_required: bool = False
    block_pipeline: bool = False


class OperationalIntentResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent_category: IntentCategory
    risk_level: RiskLevel
    confidence: float = Field(ge=0.0, le=1.0)
    signals: list[str] = Field(default_factory=list)
    effects: OperationalEffects = Field(default_factory=OperationalEffects)
    blocked_actions: list[str] = Field(default_factory=list)
    destination_team: str | None = None
    auto_reply_allowed: bool = True
    copilot_only: bool = False
    reason_code: str | None = None
    response_template_id: str | None = None
    response_template: str | None = None


__all__ = ["OperationalEffects", "OperationalIntentResult"]
