"""Tests for OpenAIComposer (happy + retries + fallback + tone passthrough)."""
import json
from decimal import Decimal

import respx
from httpx import Response

from atendia.contracts.tone import Tone
from atendia.runner.composer_canned import CannedComposer
from atendia.runner.composer_openai import OpenAIComposer
from atendia.runner.composer_protocol import ComposerInput


def _ok_composer_response(messages=None, model="gpt-4o", tokens_in=450, tokens_out=80):
    payload = {"messages": messages or ["¡Qué onda!", "¿En qué te ayudo?"]}
    return Response(
        200,
        json={
            "id": "chatcmpl-cmp", "object": "chat.completion", "created": 0,
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


# T14 — happy path

@respx.mock
async def test_compose_happy_path_returns_messages_and_usage():
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=_ok_composer_response(
            messages=["¡Qué onda, Frank!", "¿Te ayudo con tu moto?"],
        )
    )
    composer = OpenAIComposer(api_key="sk-test")
    out, usage = await composer.compose(input=ComposerInput(
        action="greet", current_stage="greeting", tone=Tone(),
    ))
    assert out.messages == ["¡Qué onda, Frank!", "¿Te ayudo con tu moto?"]
    assert usage is not None
    assert usage.tokens_in == 450
    assert usage.tokens_out == 80
    assert usage.cost_usd == Decimal("0.001925")
    assert usage.fallback_used is False
    assert usage.model == "gpt-4o"


# T15 — strict-mode schema invariants

def test_composer_schema_required_matches_properties():
    from atendia.runner.composer_openai import _composer_schema
    schema = _composer_schema(2)["schema"]
    assert set(schema["required"]) == set(schema["properties"].keys())
    assert schema["additionalProperties"] is False


def test_composer_schema_max_items_respects_input():
    from atendia.runner.composer_openai import _composer_schema
    assert _composer_schema(1)["schema"]["properties"]["messages"]["maxItems"] == 1
    assert _composer_schema(2)["schema"]["properties"]["messages"]["maxItems"] == 2
    assert _composer_schema(3)["schema"]["properties"]["messages"]["maxItems"] == 3


def test_composer_schema_min_items_is_1():
    from atendia.runner.composer_openai import _composer_schema
    assert _composer_schema(2)["schema"]["properties"]["messages"]["minItems"] == 1


# T16 — retry + fallback

@respx.mock
async def test_compose_retries_on_503_then_succeeds():
    route = respx.post("https://api.openai.com/v1/chat/completions").mock(
        side_effect=[
            Response(503, json={"error": {"message": "boom"}}),
            _ok_composer_response(),
        ]
    )
    composer = OpenAIComposer(api_key="sk-test", retry_delays_ms=(50,))
    _out, usage = await composer.compose(input=ComposerInput(
        action="greet", current_stage="greeting", tone=Tone(),
    ))
    assert route.call_count == 2
    assert usage is not None
    assert usage.fallback_used is False
    assert usage.cost_usd > Decimal("0")


@respx.mock
async def test_compose_falls_back_to_canned_on_exhaustion():
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=Response(503, json={"error": {"message": "down"}})
    )
    fallback = CannedComposer()
    composer = OpenAIComposer(
        api_key="sk-test", retry_delays_ms=(10, 20), fallback=fallback,
    )
    out, usage = await composer.compose(input=ComposerInput(
        action="greet", current_stage="greeting", tone=Tone(),
    ))
    # Output is the canned text
    assert "hola" in out.messages[0].lower()
    # Usage signals fallback
    assert usage is not None
    assert usage.fallback_used is True
    assert usage.tokens_in == 0
    assert usage.cost_usd == Decimal("0")


@respx.mock
async def test_compose_does_not_retry_on_401():
    route = respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=Response(401, json={"error": {"message": "bad key"}})
    )
    composer = OpenAIComposer(api_key="sk-test", retry_delays_ms=(10, 20))
    _out, usage = await composer.compose(input=ComposerInput(
        action="greet", current_stage="greeting", tone=Tone(),
    ))
    assert route.call_count == 1
    assert usage.fallback_used is True


@respx.mock
async def test_compose_does_not_retry_on_400():
    route = respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=Response(400, json={"error": {"message": "bad req"}})
    )
    composer = OpenAIComposer(api_key="sk-test", retry_delays_ms=(10, 20))
    _, usage = await composer.compose(input=ComposerInput(
        action="greet", current_stage="greeting", tone=Tone(),
    ))
    assert route.call_count == 1
    assert usage.fallback_used is True


@respx.mock
async def test_compose_does_not_retry_on_422():
    route = respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=Response(422, json={"error": {"message": "unprocessable"}})
    )
    composer = OpenAIComposer(api_key="sk-test", retry_delays_ms=(10, 20))
    _, usage = await composer.compose(input=ComposerInput(
        action="greet", current_stage="greeting", tone=Tone(),
    ))
    assert route.call_count == 1
    assert usage.fallback_used is True


@respx.mock
async def test_compose_treats_malformed_json_as_validation_error():
    """Output JSON that doesn't satisfy ComposerOutput → ValidationError → fail fast → fallback."""
    bad = Response(200, json={
        "id": "x", "object": "chat.completion", "created": 0,
        "model": "gpt-4o",
        "choices": [{
            "index": 0,
            # empty list violates min_length
            "message": {"role": "assistant", "content": '{"messages": []}'},
            "finish_reason": "stop",
        }],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    })
    route = respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=bad,
    )
    composer = OpenAIComposer(api_key="sk-test", retry_delays_ms=(10, 20))
    _, usage = await composer.compose(input=ComposerInput(
        action="greet", current_stage="greeting", tone=Tone(),
    ))
    assert route.call_count == 1   # ValidationError is non-retriable
    assert usage.fallback_used is True


# T17 — tone passes through to system prompt

@respx.mock
async def test_compose_passes_tone_to_prompt():
    route = respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=_ok_composer_response()
    )
    composer = OpenAIComposer(api_key="sk-test")
    await composer.compose(input=ComposerInput(
        action="greet", current_stage="greeting",
        tone=Tone(
            bot_name="DinamoBot",
            register="informal_mexicano",
            forbidden_phrases=["frase_prohibida_z"],
        ),
    ))
    req_body = json.loads(route.calls[0].request.content.decode("utf-8"))
    system = req_body["messages"][0]["content"]
    assert "DinamoBot" in system
    assert "informal_mexicano" in system
    assert "frase_prohibida_z" in system


# T18 — max_messages caps schema

@respx.mock
async def test_compose_request_uses_max_messages_in_schema():
    route = respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=_ok_composer_response()
    )
    composer = OpenAIComposer(api_key="sk-test")
    await composer.compose(input=ComposerInput(
        action="greet", current_stage="greeting", tone=Tone(),
        max_messages=3,
    ))
    req_body = json.loads(route.calls[0].request.content.decode("utf-8"))
    schema = req_body["response_format"]["json_schema"]["schema"]
    assert schema["properties"]["messages"]["maxItems"] == 3


# T19 — quote action with no_data payload

@respx.mock
async def test_compose_quote_with_no_data_includes_no_inventes():
    route = respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=_ok_composer_response(messages=["Déjame consultar y te paso el precio."])
    )
    composer = OpenAIComposer(api_key="sk-test")
    await composer.compose(input=ComposerInput(
        action="quote",
        action_payload={"status": "no_data", "hint": "catalog not connected"},
        current_stage="quote",
        extracted_data={"interes_producto": "150Z"},
        tone=Tone(),
    ))
    req_body = json.loads(route.calls[0].request.content.decode("utf-8"))
    system = req_body["messages"][0]["content"]
    assert "NO INVENTES PRECIOS" in system
    assert "150Z" in system  # extracted_data shows up
