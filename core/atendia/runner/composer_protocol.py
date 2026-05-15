"""ComposerProvider Protocol + Pydantic models for input/output.

Three implementations live in this package:
- OpenAIComposer  — real LLM (gpt-4o), used in production (T14+)
- CannedComposer  — hardcoded text per action; default and fallback (T10)

Both return (ComposerOutput, UsageMetadata | None). Mocks/canned return None usage.
"""

from typing import Protocol

from pydantic import BaseModel, Field, field_validator

from atendia.contracts.flow_mode import FlowMode
from atendia.contracts.handoff_summary import HandoffReason
from atendia.contracts.tone import Tone
from atendia.contracts.vision_result import VisionResult
from atendia.runner.nlu_protocol import UsageMetadata


class ComposerInput(BaseModel):
    action: str  # Phase 3c.1: kept for logging in turn_traces.composer_input.
    action_payload: dict = Field(default_factory=dict)
    current_stage: str
    last_intent: str | None = None
    extracted_data: dict = Field(default_factory=dict)
    history: list[tuple[str, str]] = Field(default_factory=list)
    tone: Tone
    max_messages: int = Field(default=2, ge=1, le=3)

    # Phase 3c.2 — mode-based dispatch:
    flow_mode: FlowMode = FlowMode.SUPPORT
    brand_facts: dict = Field(default_factory=dict)
    vision_result: VisionResult | None = None
    # turn_number: 1-indexed in production callers, but the legacy E2E
    # fixture runner passes 0-indexed enumerate() values; allow either.
    turn_number: int = Field(default=1, ge=0)


class ComposerOutput(BaseModel):
    messages: list[str] = Field(min_length=1, max_length=3)
    # Phase 3c.2 — when the composer asks a binary sí/no question
    # (PLAN MODE disambiguations), it sets this string so the next
    # turn's runner can apply the answer deterministically. None on
    # any non-disambiguating turn; snapshot tests treat it as an
    # additive optional field so existing fixtures stay byte-equal.
    pending_confirmation_set: str | None = None
    # Migration 045 — raw text the LLM returned before parsing. Kept on
    # the output object (rather than UsageMetadata) so canned/fallback
    # composers can also surface their canned text for the DebugPanel
    # raw-vs-final comparison. None on legacy paths that don't capture it.
    raw_llm_response: str | None = None
    # D6 — composer's hint to the runner that THIS turn should escalate
    # via human_handoffs. The runner reads this and routes through
    # persist_handoff(reason=HandoffReason(value)) when set. Must be
    # exactly one of HandoffReason enum values OR null. Validated against
    # the enum so a hallucinated value surfaces as ValidationError instead
    # of a runtime crash deeper in the handoff dispatch path.
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
