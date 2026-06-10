from __future__ import annotations

from dataclasses import dataclass
from inspect import isawaitable
from time import monotonic
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator

from atendia.agent_runtime.respond_style_turn_contract import (
    AgentContextPackage,
    AgentTurnInput,
    AgentTurnValidationResult,
    FinalTurnDecision,
    LLMFieldUpdateProposal,
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
    """Budgeted multi-round tool loop configuration.

    ``max_tool_rounds``: LLM->tools->LLM cycles allowed (1 keeps the
    original single-round behavior; compound asks typically need 2-3).
    ``max_total_tool_calls``: hard cap on executed tool calls across all
    rounds. ``max_elapsed_seconds``: optional wall-clock budget checked
    before each round.
    """

    max_tool_rounds: int = 1
    max_total_tool_calls: int = 8
    max_elapsed_seconds: float | None = None


class RespondStyleToolLoop:
    """No-live Respond-Style tool loop.

    It executes budgeted dry/fact-only tool rounds and never sends,
    persists, runs actions, emits workflow side effects, or touches legacy
    composition paths. Exhausted budgets fail closed.
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
        started = monotonic()
        decision = await self._provider.generate(turn_input=turn_input, context=context)

        # Field values the LLM extracts in any round are facts for tool
        # preconditions (validated proposals only). They are provisional
        # context — nothing is persisted here; real writes remain a later,
        # separately validated execution layer.
        provisional_by_key: dict[str, LLMFieldUpdateProposal] = {}
        all_tool_results: list[ToolExecutionResult] = []
        current_context = context
        rounds_executed = 0
        total_tool_calls = 0

        nudged_after_duplicate_requests = False
        precondition_retry_done = False
        while rounds_executed < self._config.max_tool_rounds:
            tool_calls = _accepted_tool_requests(decision)
            if not tool_calls:
                break
            # Never re-execute a tool that already succeeded: reuse its
            # result. If the model only re-requested succeeded tools, nudge
            # it once with structured feedback to write from tool_results.
            tool_calls = _deduplicate_tool_calls(tool_calls, all_tool_results)
            if not tool_calls:
                if nudged_after_duplicate_requests:
                    break
                nudged_after_duplicate_requests = True
                decision = await self._provider.generate(
                    turn_input=turn_input,
                    context=_context_with_loop_feedback(
                        current_context,
                        "All requested tools already have succeeded tool_results "
                        "in context. Do not request them again; write the "
                        "final_response from those results.",
                    ),
                )
                continue
            budget_block = self._budget_block(
                started=started,
                total_tool_calls=total_tool_calls,
                requested=len(tool_calls),
            )
            if budget_block is not None:
                return _blocked_loop_decision(
                    code=budget_block,
                    message="Tool budget exhausted; visible send remains blocked.",
                    tool_rounds=rounds_executed,
                    tool_results=all_tool_results,
                )

            for proposal in _accepted_field_writes(decision):
                provisional_by_key[proposal.field_key] = proposal
            current_context = _context_with_provisional_fields(
                context, list(provisional_by_key.values())
            )
            current_context = _context_with_tool_results(
                current_context, all_tool_results
            )

            round_results: list[ToolExecutionResult] = []
            for tool_call in tool_calls:
                result = await self._execute_fact_tool(
                    tool_call=tool_call, context=current_context
                )
                round_results.append(result)
                total_tool_calls += 1

            required_failure = _required_tool_failure(round_results)
            all_tool_results.extend(round_results)
            if required_failure is not None:
                if (
                    required_failure.status == "skipped"
                    and (required_failure.error_code or "").startswith("missing_")
                    and not precondition_retry_done
                ):
                    # F5: a required tool could not run because a precondition
                    # is unknown. Instead of going silent, ask the model ONCE
                    # to request the missing detail from the customer.
                    precondition_retry_done = True
                    decision = await self._provider.generate(
                        turn_input=turn_input,
                        context=_context_with_loop_feedback(
                            current_context,
                            f"The tool {required_failure.tool_name} could not run "
                            f"({required_failure.error_code}). Do not request it "
                            "again yet: write a final_response that naturally asks "
                            "the customer for the missing detail.",
                        ),
                    )
                    continue
                return _blocked_tool_decision(
                    required_failure,
                    all_tool_results,
                    tool_rounds=rounds_executed + 1,
                    field_writes=list(provisional_by_key.values()),
                )

            rounds_executed += 1
            current_context = _context_with_tool_results(
                _context_with_provisional_fields(
                    context, list(provisional_by_key.values())
                ),
                all_tool_results,
            )
            decision = await self._provider.generate(
                turn_input=turn_input,
                context=_context_with_loop_feedback(
                    current_context,
                    "Tool results are now present in context. If no further tool "
                    "is genuinely required, write the final_response now from "
                    "those results.",
                ),
            )

        pending_required_tool = _pending_required_tool_request(
            decision, satisfied=all_tool_results
        )
        if pending_required_tool is not None:
            return _blocked_pending_tool_decision(
                pending_required_tool,
                all_tool_results,
                tool_rounds=rounds_executed,
                field_writes=list(provisional_by_key.values()),
            )
        decision = _with_merged_field_writes(
            decision, list(provisional_by_key.values())
        )
        if (
            decision.final_message is None
            and decision.accepted_handoff is None
            and decision.validation is not None
            and decision.validation.status == "valid"
        ):
            # F4: a tool_request escaped the loop as the final decision. A
            # turn must never end silently without a structured reason.
            return _blocked_loop_decision(
                code="no_final_response_after_tools",
                message=(
                    "The model did not produce a final_response after the tool "
                    "rounds; visible send remains blocked."
                ),
                tool_rounds=rounds_executed,
                tool_results=all_tool_results,
                field_writes=list(provisional_by_key.values()),
            )
        return _with_loop_trace(
            _force_no_send(decision),
            tool_rounds=rounds_executed,
            tool_results=all_tool_results,
            blocked_reason=None,
            provisional_field_keys=list(provisional_by_key.keys()),
        )

    def _budget_block(
        self,
        *,
        started: float,
        total_tool_calls: int,
        requested: int,
    ) -> str | None:
        if total_tool_calls + requested > self._config.max_total_tool_calls:
            return "tool_call_budget_exceeded"
        if (
            self._config.max_elapsed_seconds is not None
            and monotonic() - started > self._config.max_elapsed_seconds
        ):
            return "tool_time_budget_exceeded"
        return None

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


def _accepted_field_writes(decision: FinalTurnDecision) -> list[LLMFieldUpdateProposal]:
    validation = decision.validation
    if validation is None or validation.status != "valid":
        return []
    return list(decision.accepted_field_writes)


def _context_with_provisional_fields(
    context: AgentContextPackage,
    proposals: list[LLMFieldUpdateProposal],
) -> AgentContextPackage:
    if not proposals:
        return context
    identity = dict(context.agent_identity)
    contact_state = dict(identity.get("contact_state") or {})
    provisional_keys: list[str] = []
    for proposal in proposals:
        contact_state[proposal.field_key] = proposal.value
        provisional_keys.append(proposal.field_key)
    identity["contact_state"] = contact_state
    identity["provisional_field_keys"] = provisional_keys
    missing = identity.get("missing_fields")
    if isinstance(missing, list):
        identity["missing_fields"] = [
            key for key in missing if key not in provisional_keys
        ]
    return context.model_copy(update={"agent_identity": identity})


def _with_merged_field_writes(
    decision: FinalTurnDecision,
    provisional_fields: list[LLMFieldUpdateProposal],
) -> FinalTurnDecision:
    """Carry turn-1 field proposals into the final decision so they are not
    lost when the final response does not repeat them. Final-turn proposals
    win on key collisions."""
    if not provisional_fields:
        return decision
    merged: dict[str, LLMFieldUpdateProposal] = {
        item.field_key: item for item in provisional_fields
    }
    for item in decision.accepted_field_writes:
        merged[item.field_key] = item
    merged_list = list(merged.values())
    validation = decision.validation
    if validation is not None and validation.status == "valid":
        validation = validation.model_copy(
            update={"accepted_field_writes": merged_list}
        )
    return decision.model_copy(
        update={"accepted_field_writes": merged_list, "validation": validation}
    )


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
    *,
    satisfied: list[ToolExecutionResult] | None = None,
) -> LLMToolCallProposal | None:
    succeeded = {
        result.tool_name for result in satisfied or [] if result.status == "succeeded"
    }
    for tool_call in _accepted_tool_requests(decision):
        if tool_call.required and tool_call.tool_name not in succeeded:
            return tool_call
    return None


def _deduplicate_tool_calls(
    tool_calls: list[LLMToolCallProposal],
    prior_results: list[ToolExecutionResult],
) -> list[LLMToolCallProposal]:
    succeeded = {
        result.tool_name
        for result in prior_results
        if result.status == "succeeded"
    }
    seen_this_round: set[str] = set()
    deduplicated: list[LLMToolCallProposal] = []
    for tool_call in tool_calls:
        if tool_call.tool_name in succeeded or tool_call.tool_name in seen_this_round:
            continue
        seen_this_round.add(tool_call.tool_name)
        deduplicated.append(tool_call)
    return deduplicated


def _context_with_loop_feedback(
    context: AgentContextPackage,
    feedback: str,
) -> AgentContextPackage:
    return context.model_copy(
        update={
            "validator_feedback": [
                *context.validator_feedback,
                {"feedback_for_llm": feedback, "errors": []},
            ]
        }
    )


def _blocked_pending_tool_decision(
    tool_call: LLMToolCallProposal,
    tool_results: list[ToolExecutionResult],
    *,
    tool_rounds: int,
    field_writes: list[LLMFieldUpdateProposal] | None = None,
) -> FinalTurnDecision:
    code = "tool_round_limit_reached"
    error = ValidationErrorItem(
        code=code,
        message="Required tool request remained after the allowed no-send tool rounds.",
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
        accepted_field_writes=list(field_writes or []),
        trace_metadata={
            "respond_style_tool_loop": {
                "mode": "no_send",
                "tool_rounds": tool_rounds,
                "blocked": code,
                "pending_tool_name": tool_call.tool_name,
                "tool_results": [item.model_dump(mode="json") for item in tool_results],
            }
        },
    )


def _blocked_loop_decision(
    *,
    code: str,
    message: str,
    tool_rounds: int,
    tool_results: list[ToolExecutionResult],
    field_writes: list[LLMFieldUpdateProposal] | None = None,
) -> FinalTurnDecision:
    error = ValidationErrorItem(
        code=code,
        message=message,
        path="tool_requests",
        retryable=False,
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
        accepted_field_writes=list(field_writes or []),
        trace_metadata={
            "respond_style_tool_loop": {
                "mode": "no_send",
                "tool_rounds": tool_rounds,
                "blocked": code,
                "tool_results": [item.model_dump(mode="json") for item in tool_results],
            }
        },
    )


def _blocked_tool_decision(
    result: ToolExecutionResult,
    tool_results: list[ToolExecutionResult],
    *,
    tool_rounds: int,
    field_writes: list[LLMFieldUpdateProposal] | None = None,
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
        accepted_field_writes=list(field_writes or []),
        trace_metadata={
            "respond_style_tool_loop": {
                "mode": "no_send",
                "tool_rounds": tool_rounds,
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
    provisional_field_keys: list[str],
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
                    "provisional_field_keys": provisional_field_keys,
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
