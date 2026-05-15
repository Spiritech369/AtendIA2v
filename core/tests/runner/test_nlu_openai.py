import json
from decimal import Decimal

import respx
from httpx import Response

from atendia.contracts.nlu_result import Intent
from atendia.contracts.pipeline_definition import FieldSpec
from atendia.runner.nlu_openai import OpenAINLU


def _ok_response(
    intent="ask_info",
    entities=None,
    confidence=0.9,
    sentiment="neutral",
    ambiguities=None,
    model="gpt-4o-mini",
    tokens_in=480,
    tokens_out=80,
):
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
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": json.dumps(payload)},
                    "finish_reason": "stop",
                }
            ],
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
    from atendia.runner.nlu_openai import _build_strict_schema

    schema = _build_strict_schema(["ciudad", "interes_producto"])

    def check_object(node):
        if not isinstance(node, dict):
            return
        if node.get("type") == "object":
            props = node.get("properties", {})
            req = node.get("required", [])
            assert set(req) == set(props.keys()), (
                f"required {sorted(req)} != properties {sorted(props.keys())} "
                f"on {node.get('title', '<unnamed>')}"
            )
            assert node.get("additionalProperties") is False
        if isinstance(node, dict):
            for v in node.values():
                check_object(v)

    check_object(schema["schema"])


def test_strict_schema_all_leaves_have_type():
    """No untyped Any-leaves."""
    from atendia.runner.nlu_openai import _build_strict_schema

    schema = _build_strict_schema(["ciudad"])

    def check_typed(node, path="root"):
        if not isinstance(node, dict):
            return
        if node.get("type") == "object":
            for k, v in node.get("properties", {}).items():
                if isinstance(v, dict):
                    has_disc = any(
                        d in v for d in ("type", "$ref", "anyOf", "oneOf", "allOf", "enum")
                    )
                    assert has_disc, f"{path}.{k} has no type discriminator: {v}"
                    check_typed(v, f"{path}.{k}")
        for k, v in node.items():
            if isinstance(v, dict):
                check_typed(v, f"{path}/{k}")
            elif isinstance(v, list):
                for item in v:
                    check_typed(item, f"{path}/{k}[]")

    check_typed(schema["schema"])


def test_entities_schema_has_one_property_per_field():
    from atendia.runner.nlu_openai import _build_strict_schema

    schema = _build_strict_schema(["ciudad", "interes_producto", "nombre"])
    entities = schema["schema"]["properties"]["entities"]
    assert set(entities["properties"].keys()) == {"ciudad", "interes_producto", "nombre"}
    assert set(entities["required"]) == {"ciudad", "interes_producto", "nombre"}
    assert entities["additionalProperties"] is False


def test_entities_schema_each_field_is_nullable_extractedfield():
    from atendia.runner.nlu_openai import _build_strict_schema

    schema = _build_strict_schema(["ciudad"])
    field_schema = schema["schema"]["properties"]["entities"]["properties"]["ciudad"]
    types = field_schema["anyOf"]
    has_ref = any(t.get("$ref") == "#/$defs/ExtractedField" for t in types)
    has_null = any(t.get("type") == "null" for t in types)
    assert has_ref and has_null


def test_entities_schema_with_no_fields():
    from atendia.runner.nlu_openai import _build_strict_schema

    schema = _build_strict_schema([])
    entities = schema["schema"]["properties"]["entities"]
    assert entities["type"] == "object"
    assert entities["properties"] == {}
    assert entities["required"] == []
    assert entities["additionalProperties"] is False


@respx.mock
async def test_classify_drops_null_entity_values_before_validation():
    """OpenAI strict mode emits `null` for fields the LLM can't extract.
    Adapter must drop these nulls before NLUResult.model_validate to avoid
    a Pydantic ValidationError."""
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=_ok_response(
            intent="ask_info",
            entities={
                "interes_producto": {"value": "150Z", "confidence": 0.9, "source_turn": 0},
                "ciudad": None,  # LLM had nothing — strict-mode-forced null
                "presupuesto_max": None,  # ditto
            },
        )
    )
    nlu = OpenAINLU(api_key="sk-test")
    result, usage = await nlu.classify(
        text="me interesa la 150Z",
        current_stage="qualify",
        required_fields=[
            FieldSpec(name="interes_producto", description="Modelo"),
            FieldSpec(name="ciudad", description="Ciudad"),
        ],
        optional_fields=[FieldSpec(name="presupuesto_max", description="Tope")],
        history=[],
    )
    # Only the non-null entity survives.
    assert "interes_producto" in result.entities
    assert "ciudad" not in result.entities
    assert "presupuesto_max" not in result.entities
    assert result.entities["interes_producto"].value == "150Z"
    assert usage is not None


@respx.mock
async def test_classify_drops_extracted_field_with_inner_null_value():
    """gpt-4o-mini sometimes emits {value: null, confidence: 0, source_turn: N} INSIDE the
    ExtractedField shape instead of using the null branch. Adapter must treat that as
    'no value extracted' so empty entities don't trigger the downstream ambiguity check
    via field.confidence < threshold."""
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=_ok_response(
            intent="ask_price",
            entities={
                "interes_producto": {"value": "150Z", "confidence": 0.9, "source_turn": 0},
                # The case discovered in production live smoke: LLM populates the
                # ExtractedField shape even when it has nothing.
                "ciudad": {"value": None, "confidence": 0.0, "source_turn": 0},
                "presupuesto_max": {"value": None, "confidence": 0.0, "source_turn": 0},
            },
        )
    )
    nlu = OpenAINLU(api_key="sk-test")
    result, _ = await nlu.classify(
        text="cuanto cuesta la 150Z?",
        current_stage="qualify",
        required_fields=[
            FieldSpec(name="interes_producto", description="Modelo"),
            FieldSpec(name="ciudad", description="Ciudad"),
        ],
        optional_fields=[FieldSpec(name="presupuesto_max", description="Tope")],
        history=[],
    )
    assert set(result.entities.keys()) == {"interes_producto"}, (
        f"expected only interes_producto, got {sorted(result.entities.keys())}"
    )
    assert result.entities["interes_producto"].value == "150Z"


@respx.mock
async def test_classify_retries_on_503_then_succeeds():
    """T16: transient error gets retried; 2nd attempt succeeds."""
    route = respx.post("https://api.openai.com/v1/chat/completions").mock(
        side_effect=[
            Response(503, json={"error": {"message": "boom"}}),
            _ok_response(),
        ]
    )
    nlu = OpenAINLU(api_key="sk-test", retry_delays_ms=(50,))
    result, usage = await nlu.classify(
        text="hola",
        current_stage="greeting",
        required_fields=[],
        optional_fields=[],
        history=[],
    )
    assert route.call_count == 2
    assert result.intent == Intent.ASK_INFO  # default in _ok_response
    assert usage is not None
    assert usage.cost_usd > Decimal("0")


@respx.mock
async def test_classify_returns_unclear_when_all_retries_fail():
    """T17: exhausted retries -> unclear with nlu_error ambiguity."""
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=Response(503, json={"error": {"message": "down"}})
    )
    nlu = OpenAINLU(api_key="sk-test", retry_delays_ms=(10, 20))
    result, usage = await nlu.classify(
        text="hola",
        current_stage="greeting",
        required_fields=[],
        optional_fields=[],
        history=[],
    )
    assert result.intent == Intent.UNCLEAR
    assert result.confidence == 0.0
    assert any(a.startswith("nlu_error:InternalServerError") for a in result.ambiguities)
    assert usage is not None
    assert usage.tokens_in == 0
    assert usage.cost_usd == Decimal("0")


@respx.mock
async def test_classify_retries_on_429_rate_limit():
    """T17 (variant): RateLimitError is retried, not fail-fast."""
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=Response(429, json={"error": {"message": "rate limit"}})
    )
    nlu = OpenAINLU(api_key="sk-test", retry_delays_ms=(10, 20))
    result, _ = await nlu.classify(
        text="x",
        current_stage="x",
        required_fields=[],
        optional_fields=[],
        history=[],
    )
    assert result.intent == Intent.UNCLEAR
    assert any("RateLimitError" in a for a in result.ambiguities)


@respx.mock
async def test_classify_does_not_retry_on_401():
    """T18: AuthenticationError fails fast - no retry."""
    route = respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=Response(401, json={"error": {"message": "bad key"}})
    )
    nlu = OpenAINLU(api_key="sk-test", retry_delays_ms=(10, 20))
    result, _ = await nlu.classify(
        text="x",
        current_stage="x",
        required_fields=[],
        optional_fields=[],
        history=[],
    )
    assert route.call_count == 1
    assert result.intent == Intent.UNCLEAR
    assert any("AuthenticationError" in a for a in result.ambiguities)


@respx.mock
async def test_classify_does_not_retry_on_400():
    """T18: BadRequestError fails fast - no retry."""
    route = respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=Response(400, json={"error": {"message": "bad schema"}})
    )
    nlu = OpenAINLU(api_key="sk-test", retry_delays_ms=(10, 20))
    result, _ = await nlu.classify(
        text="x",
        current_stage="x",
        required_fields=[],
        optional_fields=[],
        history=[],
    )
    assert route.call_count == 1
    assert any("BadRequestError" in a for a in result.ambiguities)


@respx.mock
async def test_classify_treats_malformed_json_as_validation_error():
    """Malformed structured-output JSON is non-retriable (temperature=0 -> identical retry = waste).
    Single attempt, fail fast, fall back to unclear."""
    bad = Response(
        200,
        json={
            "id": "x",
            "object": "chat.completion",
            "created": 0,
            "model": "gpt-4o-mini",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": '{"intent": "FAKE"}'},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        },
    )
    route = respx.post("https://api.openai.com/v1/chat/completions").mock(return_value=bad)
    nlu = OpenAINLU(api_key="sk-test", retry_delays_ms=(10, 20))
    result, _ = await nlu.classify(
        text="x",
        current_stage="x",
        required_fields=[],
        optional_fields=[],
        history=[],
    )
    assert route.call_count == 1
    assert result.intent == Intent.UNCLEAR
    assert any("ValidationError" in a for a in result.ambiguities)


@respx.mock
async def test_classify_does_not_retry_on_422_unprocessable():
    """T16-19 fix: APIStatusError catchall covers unmapped statuses (e.g., 422)."""
    route = respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=Response(422, json={"error": {"message": "unprocessable"}})
    )
    nlu = OpenAINLU(api_key="sk-test", retry_delays_ms=(10, 20))
    result, _ = await nlu.classify(
        text="x",
        current_stage="x",
        required_fields=[],
        optional_fields=[],
        history=[],
    )
    assert route.call_count == 1
    assert result.intent == Intent.UNCLEAR
    # The class name will be UnprocessableEntityError (or similar APIStatusError subclass)
    # — assert ambiguity tag is well-formed and starts with the expected prefix.
    assert any(a.startswith("nlu_error:") for a in result.ambiguities)
