from atendia.scripts.upgrade_dinamo_pipeline_to_v4 import (
    DINAMO_FIELD_DESCRIPTIONS,
    upgrade_pipeline_jsonb,
)


def test_upgrade_string_fields_to_objects():
    old = {
        "version": 3,
        "stages": [
            {
                "id": "qualify",
                "required_fields": ["interes_producto", "ciudad"],
                "actions_allowed": [],
                "transitions": [],
            }
        ],
        "tone": {},
        "fallback": "x",
    }
    new = upgrade_pipeline_jsonb(old)
    assert new["version"] == 4
    assert new["nlu"] == {"history_turns": 4}
    rfs = new["stages"][0]["required_fields"]
    assert rfs[0] == {
        "name": "interes_producto",
        "description": DINAMO_FIELD_DESCRIPTIONS["interes_producto"],
    }
    assert rfs[1]["name"] == "ciudad"
    assert rfs[1]["description"] == DINAMO_FIELD_DESCRIPTIONS["ciudad"]


def test_upgrade_idempotent_on_already_v4():
    already = {
        "version": 4,
        "nlu": {"history_turns": 4},
        "stages": [
            {
                "id": "qualify",
                "required_fields": [{"name": "interes_producto", "description": "..."}],
                "actions_allowed": [],
                "transitions": [],
            }
        ],
        "tone": {},
        "fallback": "x",
    }
    assert upgrade_pipeline_jsonb(already) == already


def test_upgrade_unknown_field_uses_empty_description():
    """For a field not in DINAMO_FIELD_DESCRIPTIONS, default to empty description."""
    old = {
        "version": 3,
        "stages": [
            {
                "id": "qualify",
                "required_fields": ["unknown_field_xyz"],
                "actions_allowed": [],
                "transitions": [],
            }
        ],
        "tone": {},
        "fallback": "x",
    }
    new = upgrade_pipeline_jsonb(old)
    assert new["stages"][0]["required_fields"][0] == {
        "name": "unknown_field_xyz",
        "description": "",
    }


def test_upgrade_handles_optional_fields_too():
    """If a stage already has optional_fields (string form), they get coerced too."""
    old = {
        "version": 3,
        "stages": [
            {
                "id": "qualify",
                "required_fields": ["ciudad"],
                "optional_fields": ["nombre"],
                "actions_allowed": [],
                "transitions": [],
            }
        ],
        "tone": {},
        "fallback": "x",
    }
    new = upgrade_pipeline_jsonb(old)
    assert new["stages"][0]["optional_fields"][0] == {
        "name": "nombre",
        "description": DINAMO_FIELD_DESCRIPTIONS["nombre"],
    }


def test_upgrade_resulting_pipeline_validates_against_pydantic():
    """Round-trip: upgraded JSONB should parse cleanly into PipelineDefinition."""
    from atendia.contracts.pipeline_definition import PipelineDefinition

    old = {
        "version": 3,
        "stages": [
            {
                "id": "qualify",
                "required_fields": ["interes_producto", "ciudad"],
                "optional_fields": ["nombre", "presupuesto_max"],
                "actions_allowed": ["ask_field"],
                "transitions": [],
            }
        ],
        "tone": {},
        "fallback": "escalate_to_human",
    }
    new = upgrade_pipeline_jsonb(old)
    p = PipelineDefinition.model_validate(new)
    assert p.version == 4
    assert p.nlu.history_turns == 4
    assert p.stages[0].required_fields[0].name == "interes_producto"
    assert p.stages[0].required_fields[0].description.startswith("Modelo")
