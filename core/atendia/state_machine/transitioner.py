from atendia.contracts.nlu_result import NLUResult
from atendia.contracts.pipeline_definition import PipelineDefinition
from atendia.state_machine.conditions import EvaluationContext, evaluate


class UnknownStageError(Exception):
    """Raised when a stage id is not in the pipeline."""


def next_stage(
    pipeline: PipelineDefinition,
    current_stage_id: str,
    nlu: NLUResult,
    extracted_data: dict,
    turn_count: int,
) -> str:
    stage = next((s for s in pipeline.stages if s.id == current_stage_id), None)
    if stage is None:
        raise UnknownStageError(current_stage_id)

    ctx = EvaluationContext(
        nlu=nlu,
        extracted_data=extracted_data,
        # Flatten FieldSpec list to bare names for runtime evaluation (T5).
        required_fields=[f.name for f in stage.required_fields],
        turn_count=turn_count,
    )
    for t in stage.transitions:
        if evaluate(t.when, ctx):
            return t.to
    return current_stage_id
