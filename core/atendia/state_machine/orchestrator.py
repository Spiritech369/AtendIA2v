from dataclasses import dataclass
from typing import Any

from atendia.contracts.conversation_state import ConversationState
from atendia.contracts.nlu_result import Intent, NLUResult
from atendia.contracts.pipeline_definition import PipelineDefinition
from atendia.state_machine.action_resolver import NoActionAvailableError, resolve_action
from atendia.state_machine.ambiguity import is_ambiguous
from atendia.state_machine.transitioner import next_stage


@dataclass
class OrchestratorDecision:
    next_stage: str
    action: str
    reason: str


def _stage_by_id(pipeline: PipelineDefinition, sid: str):
    return next(s for s in pipeline.stages if s.id == sid)


def process_turn(
    pipeline: PipelineDefinition,
    state: ConversationState,
    nlu: NLUResult,
    turn_count: int,
    turn_resolution: Any | None = None,
) -> OrchestratorDecision:
    resolution_can_continue = _turn_resolution_can_continue(turn_resolution)
    if is_ambiguous(nlu) and not resolution_can_continue:
        current_stage = _stage_by_id(pipeline, state.current_stage)
        action = (
            "ask_clarification"
            if "ask_clarification" in current_stage.actions_allowed
            else current_stage.actions_allowed[0]
            if current_stage.actions_allowed
            else pipeline.fallback
        )
        return OrchestratorDecision(
            next_stage=state.current_stage,
            action=action,
            reason="ambiguous_nlu",
        )

    flat_extracted = {k: v.value for k, v in state.extracted_data.items()}
    target_stage_id = next_stage(pipeline, state.current_stage, nlu, flat_extracted, turn_count)

    target_stage = _stage_by_id(pipeline, target_stage_id)
    try:
        effective_intent = _effective_intent(nlu, turn_resolution)
        action = resolve_action(target_stage, effective_intent)
    except NoActionAvailableError:
        action = (
            "ask_clarification"
            if "ask_clarification" in target_stage.actions_allowed
            else pipeline.fallback
            if pipeline.fallback in target_stage.actions_allowed
            else target_stage.actions_allowed[0]
            if target_stage.actions_allowed
            else pipeline.fallback
        )

    transition_reason = (
        f"transition:{state.current_stage}->{target_stage_id}"
        if target_stage_id != state.current_stage
        else "stay_in_stage"
    )
    return OrchestratorDecision(
        next_stage=target_stage_id,
        action=action,
        reason=transition_reason,
    )


def _turn_resolution_can_continue(turn_resolution: Any | None) -> bool:
    if turn_resolution is None:
        return False
    try:
        selected = turn_resolution.selected_attempt
    except AttributeError:
        return False
    return bool(
        turn_resolution.resolved
        and selected is not None
        and selected.can_write_state
        and not selected.requires_confirmation
        and selected.field_updates
    )


def _effective_intent(nlu: NLUResult, turn_resolution: Any | None) -> Intent:
    if not _turn_resolution_can_continue(turn_resolution):
        return nlu.intent
    raw_intent = getattr(turn_resolution, "effective_intent", None)
    if raw_intent:
        try:
            return Intent(str(raw_intent).upper())
        except ValueError:
            pass
    if nlu.intent == Intent.UNCLEAR:
        return Intent.ASK_INFO
    return nlu.intent
