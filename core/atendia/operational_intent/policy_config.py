from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


IntentCategory = Literal[
    "sales",
    "credit",
    "documents",
    "faq",
    "payment_sensitive",
    "human_request",
    "wrong_recipient",
    "complaint",
    "aftersales_support",
    "delivery_support",
    "unknown",
]

RiskLevel = Literal["none", "low", "medium", "high"]


class SignalConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    keywords: list[str] = Field(default_factory=list)
    semantic_examples: list[str] = Field(default_factory=list)
    semantic_labels: list[str] = Field(default_factory=list)
    channel_context: list[str] = Field(default_factory=list)
    current_stages: list[str] = Field(default_factory=list)
    state_conditions: dict[str, object] = Field(default_factory=dict)
    min_confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class PauseRuleConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pause_bot: bool = False
    block_pipeline: bool = False
    auto_reply_allowed: bool = True
    copilot_only: bool = False


class HandoffRuleConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    required: bool = False
    reason_code: str | None = None
    destination_team: str | None = None
    priority: Literal["low", "normal", "high", "urgent"] = "normal"
    use_human_availability: bool = False


class OperationalCategoryPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: IntentCategory
    enabled: bool = True
    risk_level: RiskLevel
    signals: SignalConfig = Field(default_factory=SignalConfig)
    pause_rules: PauseRuleConfig = Field(default_factory=PauseRuleConfig)
    handoff_rules: HandoffRuleConfig = Field(default_factory=HandoffRuleConfig)
    blocked_actions: list[str] = Field(default_factory=list)
    destination_team: str | None = None
    auto_reply_allowed: bool | None = None
    copilot_only: bool | None = None
    response_template_id: str | None = None

    @model_validator(mode="after")
    def _sensitive_policy_consistency(self) -> "OperationalCategoryPolicy":
        if self.handoff_rules.required and not self.pause_rules.pause_bot:
            raise ValueError(f"{self.id}: handoff_required requires pause_bot=true")
        if self.pause_rules.block_pipeline and "continue_sales_funnel" not in self.blocked_actions:
            raise ValueError(
                f"{self.id}: block_pipeline=true must block continue_sales_funnel"
            )
        return self


class PolicyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(default=1, ge=1)
    tenant_id: str
    categories: list[OperationalCategoryPolicy] = Field(min_length=1)
    handoff_teams: dict[str, dict[str, object]] = Field(default_factory=dict)
    human_availability: dict[str, object] = Field(default_factory=dict)
    templates: dict[str, str] = Field(default_factory=dict)

    @field_validator("categories")
    @classmethod
    def _unique_categories(
        cls,
        value: list[OperationalCategoryPolicy],
    ) -> list[OperationalCategoryPolicy]:
        ids = [item.id for item in value]
        if len(ids) != len(set(ids)):
            raise ValueError(f"duplicate operational categories: {ids}")
        return value


__all__ = [
    "HandoffRuleConfig",
    "IntentCategory",
    "OperationalCategoryPolicy",
    "PauseRuleConfig",
    "PolicyConfig",
    "RiskLevel",
    "SignalConfig",
]
