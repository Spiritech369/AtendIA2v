from dataclasses import dataclass

from atendia.contracts.conversation_state import ConversationState
from atendia.contracts.nlu_result import NLUResult
from atendia.contracts.pipeline_definition import PipelineDefinition
from atendia.state_machine.action_resolver import resolve_action
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
) -> OrchestratorDecision:
    if is_ambiguous(nlu):
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
    action = resolve_action(target_stage, nlu.intent)

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
