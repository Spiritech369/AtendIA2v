"""Deterministic flow router (Phase 3c.2).

Cada turno, evalúa una lista de FlowModeRule del JSONB del pipeline
y devuelve el FlowMode correspondiente. Primer match gana. La regla
'always' debe ser la última (fallback SUPPORT).

NO LLM call — es matching de keywords + state. Costo: $0, latencia: <1ms.
"""
import unicodedata
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from atendia.contracts.extracted_fields import ExtractedFields
from atendia.contracts.flow_mode import FlowMode
from atendia.contracts.nlu_result import NLUResult
from atendia.contracts.vision_result import VisionResult


class HasAttachmentTrigger(BaseModel):
    type: Literal["has_attachment"] = "has_attachment"


class KeywordInTextTrigger(BaseModel):
    type: Literal["keyword_in_text"] = "keyword_in_text"
    list: list[str]


class FieldMissingTrigger(BaseModel):
    type: Literal["field_missing"] = "field_missing"
    field: str


class FieldPresentTrigger(BaseModel):
    type: Literal["field_present"] = "field_present"
    field: str


class FieldPresentAndIntentTrigger(BaseModel):
    type: Literal["field_present_and_intent"] = "field_present_and_intent"
    field: str
    intents: list[str]


class IntentIsTrigger(BaseModel):
    type: Literal["intent_is"] = "intent_is"
    intents: list[str]


class PendingConfirmationTrigger(BaseModel):
    type: Literal["pending_confirmation"] = "pending_confirmation"


class AlwaysTrigger(BaseModel):
    type: Literal["always"] = "always"


Trigger = (
    HasAttachmentTrigger
    | KeywordInTextTrigger
    | FieldMissingTrigger
    | FieldPresentTrigger
    | FieldPresentAndIntentTrigger
    | IntentIsTrigger
    | PendingConfirmationTrigger
    | AlwaysTrigger
)


class FlowModeRule(BaseModel):
    model_config = ConfigDict(use_enum_values=False)

    id: str
    trigger: Trigger = Field(discriminator="type")
    mode: FlowMode


def pick_flow_mode(
    *,
    rules: list[FlowModeRule],
    extracted: ExtractedFields,
    nlu: NLUResult,
    vision: VisionResult | None,
    inbound_text: str,
    pending_confirmation: str | None,
) -> FlowMode:
    """Return the first FlowMode whose rule matches.

    rules MUST end with an AlwaysTrigger rule, else this raises.
    """
    normalized = _normalize_for_router(inbound_text)
    for rule in rules:
        if _matches(rule.trigger, extracted, nlu, vision, normalized, pending_confirmation):
            return rule.mode
    raise RuntimeError("flow_mode_rules MUST end with an `always` fallback rule")


def _matches(
    trigger: Trigger,
    extracted: ExtractedFields,
    nlu: NLUResult,
    vision: VisionResult | None,
    normalized_text: str,
    pending_confirmation: str | None,
) -> bool:
    if isinstance(trigger, HasAttachmentTrigger):
        return vision is not None
    if isinstance(trigger, KeywordInTextTrigger):
        return any(_normalize_for_router(kw) in normalized_text for kw in trigger.list)
    if isinstance(trigger, FieldMissingTrigger):
        return _field_value(extracted, trigger.field) in (None, False, "", 0)
    if isinstance(trigger, FieldPresentTrigger):
        return _field_value(extracted, trigger.field) not in (None, False, "", 0)
    if isinstance(trigger, FieldPresentAndIntentTrigger):
        present = _field_value(extracted, trigger.field) not in (None, False, "", 0)
        return present and nlu.intent.value in trigger.intents
    if isinstance(trigger, IntentIsTrigger):
        return nlu.intent.value in trigger.intents
    if isinstance(trigger, PendingConfirmationTrigger):
        return pending_confirmation is not None and pending_confirmation != ""
    if isinstance(trigger, AlwaysTrigger):
        return True
    return False  # unreachable; defensive


def _field_value(extracted: ExtractedFields, name: str) -> Any:
    """Read field from ExtractedFields by name; return None if missing."""
    return getattr(extracted, name, None)


def _normalize_for_router(text: str) -> str:
    """Lowercase + strip accents. Used ONLY for router keyword
    comparison. NLU and Composer receive original text."""
    nfkd = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in nfkd if not unicodedata.combining(c))
