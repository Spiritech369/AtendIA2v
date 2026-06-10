from __future__ import annotations

from dataclasses import dataclass
from inspect import isawaitable
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator

from atendia.agent_runtime.respond_style_turn_contract import (
    AgentContextPackage,
    AgentTurnInput,
    AgentTurnValidationResult,
    FinalTurnDecision,
    LLMToolCallProposal,
    ValidationErrorItem,
)

ToolExecutionStatus = Literal["succeeded", "failed", "skipped"]


class ToolExecutionResult(BaseModel):
    """Fact-only tool execution result for Respond-Style no-send loops."""

    model_config = ConfigDict(extra="forbid")

    tool_name: str
    status: ToolExecutionStatus
    facts: dict[str, Any] = Field(default_factory=dict)
    citations: list[str] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)
    error_code: str | None = None
    is_required: bool = True
    can_support_claims: bool = True

    @field_validator("tool_name")
    @classmethod
    def require_tool_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("tool_name cannot be blank")
        return cleaned


RespondStyleToolExecutionResult = ToolExecutionResult


class RespondStyleToolExecutor(Protocol):
    def execute_tool(
        self,
        tool_call: LLMToolCallProposal,
        context: AgentContextPackage,
    ) -> ToolExecutionResult: ...


class RespondStyleTurnProvider(Protocol):
    async def generate(
        self,
        *,
        turn_input: AgentTurnInput,
        context: AgentContextPackage,
    ) -> FinalTurnDecision: ...


@dataclass(frozen=True)
class RespondStyleToolLoopConfig:
    max_tool_rounds: int = 1


class RespondStyleToolLoop:
    """No-live Respond-Style tool loop.

    It executes at most one dry/fact-only tool round and never sends,
    persists, runs actions, emits workflow side effects, or touches legacy
    composition paths.
    """

    def __init__(
        self,
        *,
        provider: RespondStyleTurnProvider,
        executor: RespondStyleToolExecutor,
        config: RespondStyleToolLoopConfig | None = None,
    ) -> None:
        self._provider = provider
        self._executor = executor
        self._config = config or RespondStyleToolLoopConfig()

    async def run(
        self,
        *,
        turn_input: AgentTurnInput,
        context: AgentContextPackage,
    ) -> FinalTurnDecision:
        first_decision = await self._provider.generate(turn_input=turn_input, context=context)
        tool_calls = _accepted_tool_requests(first_decision)
        if not tool_calls or self._config.max_tool_rounds < 1:
            return _with_loop_trace(
                _force_no_send(first_decision),
                tool_rounds=0,
                tool_results=[],
                blocked_reason=None,
            )

        tool_results: list[ToolExecutionResult] = []
        for tool_call in tool_calls:
            result = await self._execute_fact_tool(tool_call=tool_call, context=context)
            tool_results.append(result)

        required_failure = _required_tool_failure(tool_results)
        if required_failure is not None:
            return _blocked_tool_decision(required_failure, tool_results)

        context_with_tools = _context_with_tool_results(context, tool_results)
        final_decision = await self._provider.generate(
            turn_input=turn_input,
            context=context_with_tools,
        )
        pending_required_tool = _pending_required_tool_request(final_decision)
        if pending_required_tool is not None:
            return _blocked_pending_tool_decision(pending_required_tool, tool_results)
        return _with_loop_trace(
            _force_no_send(final_decision),
            tool_rounds=1,
            tool_results=tool_results,
            blocked_reason=None,
        )

    async def _execute_fact_tool(
        self,
        *,
        tool_call: LLMToolCallProposal,
        context: AgentContextPackage,
    ) -> ToolExecutionResult:
        if not _tool_is_bound(tool_call.tool_name, context):
            return ToolExecutionResult(
                tool_name=tool_call.tool_name,
                status="skipped",
                facts={},
                citations=[],
                source_refs=[],
                error_code="tool_not_bound",
                is_required=tool_call.required,
                can_support_claims=False,
            )
        result = self._executor.execute_tool(tool_call, context)
        if isawaitable(result):
            result = await result
        return result


def _accepted_tool_requests(decision: FinalTurnDecision) -> list[LLMToolCallProposal]:
    validation = decision.validation
    if validation is None or validation.status != "valid":
        return []
    return list(validation.accepted_tool_requests)


def _tool_is_bound(tool_name: str, context: AgentContextPackage) -> bool:
    for schema in context.tool_schemas:
        if not isinstance(schema, dict):
            continue
        name = schema.get("tool_name") or schema.get("name") or schema.get("key")
        if name == tool_name and schema.get("enabled", True) is not False:
            return True
    return False


def _context_with_tool_results(
    context: AgentContextPackage,
    results: list[ToolExecutionResult],
) -> AgentContextPackage:
    serialized = [result.model_dump(mode="json") for result in results]
    return context.model_copy(
        update={"tool_results": [*context.tool_results, *serialized]}
    )


def _required_tool_failure(
    results: list[ToolExecutionResult],
) -> ToolExecutionResult | None:
    for result in results:
        if result.is_required and result.status != "succeeded":
            return result
    return None


def _pending_required_tool_request(
    decision: FinalTurnDecision,
) -> LLMToolCallProposal | None:
    for tool_call in _accepted_tool_requests(decision):
        if tool_call.required:
            return tool_call
    return None


def _blocked_pending_tool_decision(
    tool_call: LLMToolCallProposal,
    tool_results: list[ToolExecutionResult],
) -> FinalTurnDecision:
    code = "tool_round_limit_reached"
    error = ValidationErrorItem(
        code=code,
        message="Required tool request remained after the allowed no-send tool round.",
        path="tool_requests",
        retryable=False,
        metadata={"tool_name": tool_call.tool_name},
    )
    validation = AgentTurnValidationResult(
        status="blocked",
        blocked_items=[error],
        send_decision="no_send",
        blocked_reason=code,
    )
    return FinalTurnDecision(
        final_message=None,
        send_decision="no_send",
        validation=validation,
        trace_metadata={
            "respond_style_tool_loop": {
                "mode": "no_send",
                "tool_rounds": 1,
                "blocked": code,
                "pending_tool_name": tool_call.tool_name,
                "tool_results": [item.model_dump(mode="json") for item in tool_results],
            }
        },
    )


def _blocked_tool_decision(
    result: ToolExecutionResult,
    tool_results: list[ToolExecutionResult],
) -> FinalTurnDecision:
    code = "required_tool_not_succeeded"
    if result.status == "failed" and result.error_code:
        code = f"required_tool_failed:{result.error_code}"
    if result.status == "skipped" and result.error_code:
        code = f"required_tool_skipped:{result.error_code}"
    error = ValidationErrorItem(
        code=code,
        message="Required fact tool did not succeed; visible send remains blocked.",
        path="tool_results",
        retryable=False,
        metadata={"tool_name": result.tool_name, "status": result.status},
    )
    validation = AgentTurnValidationResult(
        status="blocked",
        blocked_items=[error],
        send_decision="no_send",
        blocked_reason=code,
    )
    return FinalTurnDecision(
        final_message=None,
        send_decision="no_send",
        validation=validation,
        trace_metadata={
            "respond_style_tool_loop": {
                "mode": "no_send",
                "tool_rounds": 1,
                "blocked": code,
                "tool_results": [item.model_dump(mode="json") for item in tool_results],
            }
        },
    )


def _force_no_send(decision: FinalTurnDecision) -> FinalTurnDecision:
    validation = decision.validation
    if validation is not None and validation.status == "valid":
        validation = validation.model_copy(update={"send_decision": "no_send"})
    return decision.model_copy(update={"send_decision": "no_send", "validation": validation})


def _with_loop_trace(
    decision: FinalTurnDecision,
    *,
    tool_rounds: int,
    tool_results: list[ToolExecutionResult],
    blocked_reason: str | None,
) -> FinalTurnDecision:
    return decision.model_copy(
        update={
            "send_decision": "no_send",
            "trace_metadata": {
                **decision.trace_metadata,
                "respond_style_tool_loop": {
                    "mode": "no_send",
                    "tool_rounds": tool_rounds,
                    "blocked": blocked_reason,
                    "tool_results": [item.model_dump(mode="json") for item in tool_results],
                    "side_effects": {
                        "delivery": False,
                        "workflows": False,
                        "actions": False,
                    },
                },
            },
        }
    )


__all__ = [
    "RespondStyleToolExecutionResult",
    "RespondStyleToolExecutor",
    "RespondStyleToolLoop",
    "RespondStyleToolLoopConfig",
    "ToolExecutionResult",
]
