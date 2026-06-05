"""Legacy ComposerProvider Protocol + Pydantic models for input/output.

Runtime Composer is OpenAI-backed. Tests may provide local ComposerProvider
doubles, but there is no shared canned runtime composer. This contract is
kept for ConversationRunner fallback; AgentRuntime v2 owns visible copy through
TurnOutput.final_message.
"""

from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator

from atendia.contracts.flow_mode import FlowMode
from atendia.contracts.handoff_summary import HandoffReason
from atendia.contracts.tone import Tone
from atendia.contracts.vision_result import VisionResult
from atendia.runner.nlu_protocol import UsageMetadata
from atendia.runner.response_frame import ResponseFrame


class ComposerContextPack(BaseModel):
    """Explicit operational context the Composer must write from.

    This is intentionally redundant with lower-level fields such as
    ``action_payload`` and ``decision_payload``. Those fields remain the raw
    source of truth; this pack is the clean "what matters this turn" view that
    prevents the Composer from rediscovering flow state from scattered inputs.
    """

    user_message: str
    recent_history: list[str] = Field(default_factory=list)
    conversation_summary: str | None = None
    state_facts: dict[str, Any] = Field(default_factory=dict)
    business_facts: dict[str, Any] = Field(default_factory=dict)
    tool_payload: dict[str, Any] = Field(default_factory=dict)
    runner_decision: dict[str, Any] = Field(default_factory=dict)
    must_answer_first: str | None = None
    current_questions: list[dict[str, Any]] = Field(default_factory=list)
    required_answer_targets: list[str] = Field(default_factory=list)
    unresolved_intents: list[str] = Field(default_factory=list)
    pending_to_resume: dict[str, Any] | None = None
    must_not_say: list[str] = Field(default_factory=list)


class ComposerInput(BaseModel):
    action: str
    action_payload: dict = Field(default_factory=dict)
    decision_payload: dict = Field(default_factory=dict)
    context_pack: ComposerContextPack | None = None
    response_frame: ResponseFrame | None = None
    current_stage: str
    last_intent: str | None = None
    extracted_data: dict = Field(default_factory=dict)
    history: list[tuple[str, str]] = Field(default_factory=list)
    tone: Tone
    max_messages: int = Field(default=2, ge=1, le=3)
    flow_mode: FlowMode = FlowMode.SUPPORT
    mode_guidance: str | None = None
    agent_system_prompt: str | None = None
    guardrails: list[str] = Field(default_factory=list)
    brand_facts: dict = Field(default_factory=dict)
    customer_field_context: dict[str, Any] = Field(default_factory=dict)
    vision_result: VisionResult | None = None
    turn_number: int = Field(default=1, ge=0)


class ComposerOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    messages: list[str] = Field(min_length=1, max_length=3)
    pending_confirmation_set: str | None = None
    raw_llm_response: str | None = None
    suggested_handoff: str | None = None

    @field_validator("suggested_handoff")
    @classmethod
    def _validate_handoff_value(cls, v: str | None) -> str | None:
        if v is None:
            return v
        allowed = {r.value for r in HandoffReason}
        if v not in allowed:
            raise ValueError(
                f"suggested_handoff must be one of {sorted(allowed)} or null, got {v!r}"
            )
        return v


class ComposerProvider(Protocol):
    async def compose(
        self,
        *,
        input: ComposerInput,
    ) -> tuple[ComposerOutput, UsageMetadata | None]: ...
