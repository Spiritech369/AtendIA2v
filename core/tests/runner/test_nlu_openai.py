import json
from decimal import Decimal

import respx
from httpx import Response

from atendia.contracts.nlu_result import Intent
from atendia.contracts.pipeline_definition import FieldSpec
from atendia.runner.nlu_openai import OpenAINLU


def _ok_response(intent="ask_info", entities=None, confidence=0.9,
                 sentiment="neutral", ambiguities=None,
                 model="gpt-4o-mini", tokens_in=480, tokens_out=80):
    payload = {
        "intent": intent,
        "entities": entities or {},
        "confidence": confidence,
        "sentiment": sentiment,
        "ambiguities": ambiguities or [],
    }
    return Response(
        200,
        json={
            "id": "chatcmpl-x",
            "object": "chat.completion",
            "created": 0,
            "model": model,
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": json.dumps(payload)},
                "finish_reason": "stop",
            }],
            "usage": {
                "prompt_tokens": tokens_in,
                "completion_tokens": tokens_out,
                "total_tokens": tokens_in + tokens_out,
            },
        },
    )


@respx.mock
async def test_classify_happy_path_returns_result_and_usage():
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=_ok_response(
            intent="ask_price",
            entities={"interes_producto": {"value": "150Z", "confidence": 0.9, "source_turn": 0}},
        )
    )

    nlu = OpenAINLU(api_key="sk-test")
    result, usage = await nlu.classify(
        text="cuánto cuesta la 150Z?",
        current_stage="qualify",
        required_fields=[FieldSpec(name="interes_producto", description="Modelo")],
        optional_fields=[],
        history=[],
    )

    assert result.intent == Intent.ASK_PRICE
    assert result.entities["interes_producto"].value == "150Z"
    assert result.confidence == 0.9
    assert usage is not None
    assert usage.tokens_in == 480
    assert usage.tokens_out == 80
    assert usage.cost_usd == Decimal("0.000120")
    assert usage.latency_ms >= 0
    assert usage.model == "gpt-4o-mini"


def test_strict_schema_required_matches_properties():
    """OpenAI strict mode requires `required` to list every key in `properties`."""
    from atendia.runner.nlu_openai import _NLU_JSON_SCHEMA

    def check_object(node):
        if not isinstance(node, dict):
            return
        if node.get("type") == "object":
            props = node.get("properties", {})
            req = node.get("required", [])
            assert set(req) == set(props.keys()), (
                f"required {sorted(req)} != properties {sorted(props.keys())} on {node.get('title', '<unnamed>')}"
            )
            assert node.get("additionalProperties") is False, (
                f"object missing additionalProperties: false on {node.get('title', '<unnamed>')}"
            )
        for v in node.values() if isinstance(node, dict) else []:
            check_object(v)

    check_object(_NLU_JSON_SCHEMA["schema"])


def test_strict_schema_all_leaves_have_type():
    """No untyped Any-leaves (OpenAI strict mode rejects {'title': 'X'} with no type)."""
    from atendia.runner.nlu_openai import _NLU_JSON_SCHEMA

    def check_typed(node, path="root"):
        if not isinstance(node, dict):
            return
        if node.get("type") == "object":
            for k, v in node.get("properties", {}).items():
                if isinstance(v, dict):
                    has_disc = any(d in v for d in ("type", "$ref", "anyOf", "oneOf", "allOf", "enum"))
                    assert has_disc, f"{path}.{k} has no type discriminator: {v}"
                    check_typed(v, f"{path}.{k}")
        # Walk all dict values in case of nested $defs etc.
        for k, v in node.items():
            if isinstance(v, dict):
                check_typed(v, f"{path}/{k}")
            elif isinstance(v, list):
                for item in v:
                    check_typed(item, f"{path}/{k}[]")

    check_typed(_NLU_JSON_SCHEMA["schema"])
