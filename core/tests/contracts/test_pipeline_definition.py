import pytest
from pydantic import ValidationError

from atendia.contracts.pipeline_definition import (
    FieldSpec,
    NLUConfig,
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
    assert [f.name for f in p.stages[1].required_fields] == ["interes_producto", "ciudad"]


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


def test_field_spec_from_string():
    f = FieldSpec.model_validate("ciudad")
    assert f.name == "ciudad"
    assert f.description == ""


def test_field_spec_from_dict():
    f = FieldSpec.model_validate({"name": "ciudad", "description": "Ciudad del cliente"})
    assert f.name == "ciudad"
    assert f.description == "Ciudad del cliente"


def test_field_spec_rejects_invalid_name():
    with pytest.raises(ValueError):
        FieldSpec.model_validate({"name": "BadName!", "description": ""})


def test_field_spec_rejects_trailing_newline():
    with pytest.raises(ValueError):
        FieldSpec.model_validate("ciudad\n")


def test_nlu_config_defaults():
    cfg = NLUConfig()
    assert cfg.history_turns == 2


def test_nlu_config_validates_range():
    with pytest.raises(ValidationError):
        NLUConfig(history_turns=11)
    with pytest.raises(ValidationError):
        NLUConfig(history_turns=-1)


def test_stage_with_optional_fields_and_field_specs():
    s = StageDefinition.model_validate({
        "id": "qualify",
        "required_fields": [{"name": "ciudad", "description": "Ciudad"}],
        "optional_fields": ["nombre"],
        "actions_allowed": ["ask_field"],
        "transitions": [],
    })
    assert s.required_fields[0].name == "ciudad"
    assert s.required_fields[0].description == "Ciudad"
    assert s.optional_fields[0].name == "nombre"
    assert s.optional_fields[0].description == ""


def test_pipeline_with_nlu_block():
    p = PipelineDefinition.model_validate({
        "version": 4,
        "nlu": {"history_turns": 4},
        "stages": [{"id": "qualify", "actions_allowed": [], "transitions": []}],
        "tone": {},
        "fallback": "x",
    })
    assert p.nlu.history_turns == 4


def test_pipeline_default_nlu_block():
    p = PipelineDefinition.model_validate({
        "version": 4,
        "stages": [{"id": "qualify", "actions_allowed": [], "transitions": []}],
        "tone": {},
        "fallback": "x",
    })
    assert p.nlu.history_turns == 2


def test_stage_default_optional_fields_is_empty():
    s = StageDefinition.model_validate({
        "id": "qualify",
        "actions_allowed": [],
        "transitions": [],
    })
    assert s.optional_fields == []


def test_stage_rejects_field_in_both_required_and_optional():
    with pytest.raises(ValidationError):
        StageDefinition.model_validate({
            "id": "qualify",
            "required_fields": [{"name": "ciudad", "description": "Ciudad"}],
            "optional_fields": ["ciudad"],
            "actions_allowed": [],
            "transitions": [],
        })
