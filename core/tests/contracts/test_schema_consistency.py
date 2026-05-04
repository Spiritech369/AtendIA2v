import json
from pathlib import Path

import jsonschema  # type: ignore[import-untyped]

from atendia.contracts.event import Event
from atendia.contracts.message import Message
from atendia.contracts.nlu_result import NLUResult
from atendia.contracts.pipeline_definition import PipelineDefinition

CONTRACTS_DIR = Path(__file__).resolve().parents[3] / "contracts"
_SCHEMAS_DIR = Path(__file__).resolve().parents[2].parent / "contracts"


def _required_fields(schema: dict) -> set[str]:
    return set(schema.get("required", []))


def _enum_values(schema: dict, prop: str) -> set[str] | None:
    p = schema.get("properties", {}).get(prop, {})
    if "enum" in p:
        return set(p["enum"])
    return None


def test_message_required_match():
    canonical = json.loads((CONTRACTS_DIR / "message.schema.json").read_text())
    pydantic = Message.model_json_schema()
    assert _required_fields(canonical) <= _required_fields(pydantic)


def test_message_direction_enum_match():
    canonical = json.loads((CONTRACTS_DIR / "message.schema.json").read_text())
    canonical_enum = _enum_values(canonical, "direction")
    pydantic_schema = Message.model_json_schema()
    pydantic_enum = set(pydantic_schema["$defs"]["MessageDirection"]["enum"])
    assert canonical_enum == pydantic_enum


def test_event_type_enum_match():
    canonical = json.loads((CONTRACTS_DIR / "event.schema.json").read_text())
    canonical_enum = _enum_values(canonical, "type")
    pydantic_schema = Event.model_json_schema()
    pydantic_enum = set(pydantic_schema["$defs"]["EventType"]["enum"])
    assert canonical_enum == pydantic_enum


def test_pipeline_definition_required():
    canonical = json.loads((CONTRACTS_DIR / "pipeline_definition.schema.json").read_text())
    pydantic = PipelineDefinition.model_json_schema()
    assert _required_fields(canonical) <= _required_fields(pydantic)


def test_nlu_intent_enum_match():
    canonical = json.loads((CONTRACTS_DIR / "nlu_result.schema.json").read_text())
    canonical_enum = _enum_values(canonical, "intent")
    pydantic_schema = NLUResult.model_json_schema()
    pydantic_enum = set(pydantic_schema["$defs"]["Intent"]["enum"])
    assert canonical_enum == pydantic_enum


def test_pipeline_v4_blob_validates_in_both_canonical_and_pydantic():
    schema = json.loads((_SCHEMAS_DIR / "pipeline_definition.schema.json").read_text())
    blob = {
        "version": 4,
        "nlu": {"history_turns": 4},
        "stages": [
            {
                "id": "qualify",
                "required_fields": [
                    {"name": "ciudad", "description": "Ciudad del cliente"},
                    "interes_producto",  # string-shorthand form
                ],
                "optional_fields": ["nombre"],
                "actions_allowed": ["ask_field"],
                "transitions": [],
            },
        ],
        "tone": {},
        "fallback": "escalate_to_human",
    }
    jsonschema.Draft202012Validator(schema).validate(blob)
    p = PipelineDefinition.model_validate(blob)
    assert p.nlu.history_turns == 4
    assert p.stages[0].required_fields[0].name == "ciudad"
    assert p.stages[0].required_fields[1].name == "interes_producto"
    assert p.stages[0].optional_fields[0].name == "nombre"
