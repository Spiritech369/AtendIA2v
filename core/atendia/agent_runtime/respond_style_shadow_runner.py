from __future__ import annotations

import re
from inspect import isawaitable
from typing import Any, Literal, Protocol
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from atendia.agent_runtime.respond_style_tool_loop import RespondStyleToolLoop
from atendia.agent_runtime.respond_style_turn_contract import (
    AgentContextPackage,
    AgentTurnInput,
    FinalTurnDecision,
)

Recommendation = Literal[
    "prefer_respond_style",
    "prefer_current_path",
    "needs_review",
]

_INTERNAL_TEXT_RE = re.compile(
    r"\b(json|trace|prompt|debug|statewriter|state writer|validator|policy)\b",
    re.IGNORECASE,
)
_GENERIC_COPY_RE = re.compile(
    r"\b(i am here to help|how can i help|happy to assist|more information|"
    r"available to help|support team|at your service)\b",
    re.IGNORECASE,
)
_FORM_LIKE_RE = re.compile(
    r"\b(full name|phone number|email address|fill out|complete the form|"
    r"provide the following)\b",
    re.IGNORECASE,
)


class CurrentPathShadowOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    available: bool = True
    final_message: str | None = None
    tools: list[dict[str, Any]] = Field(default_factory=list)
    field_updates: list[dict[str, Any]] = Field(default_factory=list)
    validation_result: dict[str, Any] = Field(default_factory=dict)
    send_decision: str = "no_send"
    unavailable_reason: str | None = None

    @model_validator(mode="after")
    def force_no_send(self) -> CurrentPathShadowOutput:
        self.send_decision = "no_send"
        return self


class RespondStylePathShadowOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    final_message: str | None = None
    tools: list[dict[str, Any]] = Field(default_factory=list)
    tool_results: list[dict[str, Any]] = Field(default_factory=list)
    field_updates: list[dict[str, Any]] = Field(default_factory=list)
    workflow_events: list[dict[str, Any]] = Field(default_factory=list)
    validation_result: dict[str, Any] = Field(default_factory=dict)
    retry_instruction: dict[str, Any] | None = None
    send_decision: str = "no_send"

    @field_validator("send_decision")
    @classmethod
    def require_no_send(cls, value: str) -> str:
        if value != "no_send":
            raise ValueError("respond-style shadow output must remain no_send")
        return value


class CopyQualityScore(BaseModel):
    model_config = ConfigDict(extra="forbid")

    naturalness: int = Field(ge=1, le=5)
    intent_response: int = Field(ge=1, le=5)
    continuity: int = Field(ge=1, le=5)
    commercial_progress: int = Field(ge=1, le=5)
    not_form_like: int = Field(ge=1, le=5)
    no_internal_language: int = Field(ge=1, le=5)
    supported_facts: int = Field(ge=1, le=5)
    whatsapp_brevity: int = Field(ge=1, le=5)
    total: int = Field(ge=8, le=40)
    reasons: list[str] = Field(default_factory=list)


class ShadowComparison(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_score: CopyQualityScore
    respond_style_score: CopyQualityScore
    responds_to_user_intent_better: bool
    less_robotic: bool
    uses_supported_facts: bool
    has_internal_leaks: bool
    has_legacy_copy: bool
    recommendation: Recommendation
    reasons: list[str] = Field(default_factory=list)


class ShadowRunResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    tenant_id: str
    agent_id: str
    conversation_id: str
    input_summary: str
    current_path: CurrentPathShadowOutput
    respond_style_path: RespondStylePathShadowOutput
    comparison: ShadowComparison
    final_decision: str = "no_send"
    side_effects: dict[str, bool] = Field(
        default_factory=lambda: {"delivery": False, "workflows": False, "actions": False}
    )

    @field_validator("final_decision")
    @classmethod
    def require_final_no_send(cls, value: str) -> str:
        if value != "no_send":
            raise ValueError("shadow runner final decision must remain no_send")
        return value


RespondStyleShadowRunResult = ShadowRunResult


class CurrentPathShadowAdapter(Protocol):
    def run_current_path(
        self,
        *,
        turn_input: AgentTurnInput,
        context: AgentContextPackage,
    ) -> CurrentPathShadowOutput: ...


class RespondStyleShadowRunner:
    """No-live comparator between an injected current path and Respond-Style."""

    def __init__(
        self,
        *,
        respond_style_loop: RespondStyleToolLoop,
        current_path: CurrentPathShadowAdapter | None = None,
    ) -> None:
        self._respond_style_loop = respond_style_loop
        self._current_path = current_path

    async def run(
        self,
        *,
        turn_input: AgentTurnInput,
        context: AgentContextPackage,
    ) -> ShadowRunResult:
        current_output = await self._run_current_path(
            turn_input=turn_input,
            context=context,
        )
        respond_decision = await self._respond_style_loop.run(
            turn_input=turn_input,
            context=context,
        )
        respond_output = respond_style_output_from_decision(respond_decision)
        comparison = compare_shadow_outputs(
            inbound_text=turn_input.inbound_text,
            current=current_output,
            respond_style=respond_output,
        )
        return ShadowRunResult(
            run_id=f"respond-style-shadow-{uuid4().hex}",
            tenant_id=turn_input.tenant_id,
            agent_id=turn_input.agent_id,
            conversation_id=turn_input.conversation_id,
            input_summary=_input_summary(turn_input),
            current_path=current_output,
            respond_style_path=respond_output,
            comparison=comparison,
            final_decision="no_send",
        )

    async def _run_current_path(
        self,
        *,
        turn_input: AgentTurnInput,
        context: AgentContextPackage,
    ) -> CurrentPathShadowOutput:
        if self._current_path is None:
            return CurrentPathShadowOutput(
                available=False,
                final_message=None,
                unavailable_reason="current_path_adapter_not_configured",
            )
        result = self._current_path.run_current_path(
            turn_input=turn_input,
            context=context,
        )
        if isawaitable(result):
            result = await result
        return result.model_copy(update={"send_decision": "no_send"})


def respond_style_output_from_decision(
    decision: FinalTurnDecision,
) -> RespondStylePathShadowOutput:
    validation = (
        decision.validation.model_dump(mode="json")
        if decision.validation is not None
        else {}
    )
    retry = (
        decision.retry_instruction.model_dump(mode="json")
        if decision.retry_instruction is not None
        else None
    )
    loop_trace = decision.trace_metadata.get("respond_style_tool_loop", {})
    tool_results = loop_trace.get("tool_results") or []
    tools = [
        {"tool_name": item.get("tool_name"), "status": item.get("status")}
        for item in tool_results
        if isinstance(item, dict)
    ]
    return RespondStylePathShadowOutput(
        final_message=decision.final_message,
        tools=tools,
        tool_results=list(tool_results),
        field_updates=[item.model_dump(mode="json") for item in decision.accepted_field_writes],
        workflow_events=[
            item.model_dump(mode="json") for item in decision.accepted_workflow_events
        ],
        validation_result=validation,
        retry_instruction=retry,
        send_decision="no_send",
    )


def compare_shadow_outputs(
    *,
    inbound_text: str,
    current: CurrentPathShadowOutput,
    respond_style: RespondStylePathShadowOutput,
) -> ShadowComparison:
    current_score = score_copy(
        inbound_text=inbound_text,
        text=current.final_message,
        supported=bool(current.validation_result.get("status") in {"valid", "ok"})
        or bool(current.tools),
    )
    respond_score = score_copy(
        inbound_text=inbound_text,
        text=respond_style.final_message,
        supported=_respond_style_has_supported_facts(respond_style),
    )
    current_text = current.final_message or ""
    respond_text = respond_style.final_message or ""
    current_leak = _has_internal_leak(current_text)
    respond_leak = _has_internal_leak(respond_text)
    current_generic = _has_generic_copy(current_text)
    respond_generic = _has_generic_copy(respond_text)
    recommendation = _recommend(
        current_score=current_score,
        respond_score=respond_score,
        current_available=current.available,
        respond_style=respond_style,
        current_leak=current_leak,
        respond_leak=respond_leak,
    )
    return ShadowComparison(
        current_score=current_score,
        respond_style_score=respond_score,
        responds_to_user_intent_better=respond_score.intent_response
        > current_score.intent_response,
        less_robotic=respond_score.naturalness > current_score.naturalness,
        uses_supported_facts=respond_score.supported_facts >= current_score.supported_facts,
        has_internal_leaks=current_leak or respond_leak,
        has_legacy_copy=current_generic or respond_generic,
        recommendation=recommendation,
        reasons=_comparison_reasons(
            current_score=current_score,
            respond_score=respond_score,
            current_leak=current_leak,
            respond_leak=respond_leak,
            current_generic=current_generic,
            respond_generic=respond_generic,
        ),
    )


def score_copy(*, inbound_text: str, text: str | None, supported: bool) -> CopyQualityScore:
    value = (text or "").strip()
    if not value:
        return CopyQualityScore(
            naturalness=1,
            intent_response=1,
            continuity=1,
            commercial_progress=1,
            not_form_like=5,
            no_internal_language=5,
            supported_facts=5 if supported else 2,
            whatsapp_brevity=5,
            total=21,
            reasons=["no customer copy produced"],
        )
    reasons: list[str] = []
    naturalness = 4
    if _has_generic_copy(value):
        naturalness = 2
        reasons.append("generic copy detected")
    if _FORM_LIKE_RE.search(value):
        reasons.append("form-like language detected")
    intent_response = 4 if _shares_meaningful_token(inbound_text, value) else 3
    if "?" in value and len(value) <= 180:
        continuity = 4
    else:
        continuity = 3
    commercial_progress = 4 if _has_next_step(value) else 3
    not_form_like = 2 if _FORM_LIKE_RE.search(value) else 5
    no_internal_language = 1 if _has_internal_leak(value) else 5
    if no_internal_language == 1:
        reasons.append("internal language detected")
    supported_facts = 5 if supported else 3
    whatsapp_brevity = 5 if len(value) <= 450 else 2
    total = sum(
        [
            naturalness,
            intent_response,
            continuity,
            commercial_progress,
            not_form_like,
            no_internal_language,
            supported_facts,
            whatsapp_brevity,
        ]
    )
    return CopyQualityScore(
        naturalness=naturalness,
        intent_response=intent_response,
        continuity=continuity,
        commercial_progress=commercial_progress,
        not_form_like=not_form_like,
        no_internal_language=no_internal_language,
        supported_facts=supported_facts,
        whatsapp_brevity=whatsapp_brevity,
        total=total,
        reasons=reasons,
    )


def _respond_style_has_supported_facts(output: RespondStylePathShadowOutput) -> bool:
    if output.tool_results:
        return any(item.get("status") == "succeeded" for item in output.tool_results)
    validation_status = output.validation_result.get("status")
    return validation_status == "valid" and output.final_message is not None


def _recommend(
    *,
    current_score: CopyQualityScore,
    respond_score: CopyQualityScore,
    current_available: bool,
    respond_style: RespondStylePathShadowOutput,
    current_leak: bool,
    respond_leak: bool,
) -> Recommendation:
    if respond_style.send_decision != "no_send" or respond_leak:
        return "needs_review"
    if not current_available:
        return "prefer_respond_style"
    if current_leak:
        return "prefer_respond_style"
    if respond_score.total >= current_score.total:
        return "prefer_respond_style"
    return "prefer_current_path"


def _comparison_reasons(
    *,
    current_score: CopyQualityScore,
    respond_score: CopyQualityScore,
    current_leak: bool,
    respond_leak: bool,
    current_generic: bool,
    respond_generic: bool,
) -> list[str]:
    reasons = [
        f"current_score={current_score.total}",
        f"respond_style_score={respond_score.total}",
    ]
    if current_leak:
        reasons.append("current path has internal language")
    if respond_leak:
        reasons.append("respond-style path has internal language")
    if current_generic:
        reasons.append("current path has generic copy")
    if respond_generic:
        reasons.append("respond-style path has generic copy")
    return reasons


def _has_internal_leak(text: str) -> bool:
    return bool(_INTERNAL_TEXT_RE.search(text))


def _has_generic_copy(text: str) -> bool:
    return bool(_GENERIC_COPY_RE.search(text))


def _has_next_step(text: str) -> bool:
    return bool("?" in text or re.search(r"\b(check|verify|confirm|tell|send)\b", text, re.I))


def _shares_meaningful_token(inbound_text: str, text: str) -> bool:
    inbound_tokens = _meaningful_tokens(inbound_text)
    output_tokens = _meaningful_tokens(text)
    return bool(inbound_tokens & output_tokens)


def _meaningful_tokens(text: str) -> set[str]:
    stop = {
        "the",
        "and",
        "you",
        "for",
        "that",
        "with",
        "para",
        "que",
        "con",
        "una",
        "del",
        "los",
        "las",
        "por",
    }
    return {
        token
        for token in re.findall(r"[a-zA-ZáéíóúÁÉÍÓÚñÑ0-9]+", text.casefold())
        if len(token) >= 3 and token not in stop
    }


def _input_summary(turn_input: AgentTurnInput) -> str:
    text = " ".join(turn_input.inbound_text.split())
    return text[:160]


__all__ = [
    "CopyQualityScore",
    "CurrentPathShadowAdapter",
    "CurrentPathShadowOutput",
    "RespondStylePathShadowOutput",
    "RespondStyleShadowRunResult",
    "RespondStyleShadowRunner",
    "ShadowComparison",
    "ShadowRunResult",
    "compare_shadow_outputs",
    "respond_style_output_from_decision",
    "score_copy",
]
