import pytest
from pydantic import ValidationError

from atendia.contracts.pipeline_definition import (
    PipelineDefinition,
    StageDefinition,
    Transition,
)


def test_pipeline_minimal_valid():
    p = PipelineDefinition(
        version=1,
        stages=[
            StageDefinition(
                id="greeting",
                actions_allowed=["greet"],
                transitions=[Transition(to="qualify", when="intent in [ask_info, ask_price]")],
            ),
            StageDefinition(
                id="qualify",
                required_fields=["interes_producto", "ciudad"],
                actions_allowed=["ask_field", "lookup_faq"],
                transitions=[],
            ),
        ],
        tone={"register": "informal_mexicano", "use_emojis": "sparingly"},
        fallback="escalate_to_human",
    )
    assert p.stages[0].id == "greeting"
    assert p.stages[1].required_fields == ["interes_producto", "ciudad"]


def test_pipeline_duplicate_stage_id_raises():
    with pytest.raises(ValidationError):
        PipelineDefinition(
            version=1,
            stages=[
                StageDefinition(id="qualify", actions_allowed=[], transitions=[]),
                StageDefinition(id="qualify", actions_allowed=[], transitions=[]),
            ],
            tone={},
            fallback="escalate_to_human",
        )


def test_transition_to_unknown_stage_raises():
    with pytest.raises(ValidationError):
        PipelineDefinition(
            version=1,
            stages=[
                StageDefinition(
                    id="greeting",
                    actions_allowed=[],
                    transitions=[Transition(to="nonexistent", when="true")],
                ),
            ],
            tone={},
            fallback="escalate_to_human",
        )
