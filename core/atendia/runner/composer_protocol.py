"""ComposerProvider Protocol + Pydantic models for input/output.

Three implementations live in this package:
- OpenAIComposer  — real LLM (gpt-4o), used in production (T14+)
- CannedComposer  — hardcoded text per action; default and fallback (T10)

Both return (ComposerOutput, UsageMetadata | None). Mocks/canned return None usage.
"""
from typing import Protocol

from pydantic import BaseModel, Field

from atendia.contracts.flow_mode import FlowMode
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
    turn_number: int = Field(default=1, ge=1)


class ComposerOutput(BaseModel):
    messages: list[str] = Field(min_length=1, max_length=3)


class ComposerProvider(Protocol):
    async def compose(
        self, *, input: ComposerInput,
    ) -> tuple[ComposerOutput, UsageMetadata | None]: ...
