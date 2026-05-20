import json
from decimal import Decimal

import pytest
import respx
from httpx import Response

from atendia.contracts.tone import Tone
from atendia.runner.composer_openai import ComposerProviderError, OpenAIComposer
from atendia.runner.composer_protocol import ComposerInput


def _ok_composer_response(messages=None, model="gpt-4o", tokens_in=450, tokens_out=80):
    payload = {"messages": messages or ["Hola", "¿En qué te ayudo?"], "suggested_handoff": None}
    return Response(
        200,
        json={
            "id": "chatcmpl-cmp",
            "model": model,
            "choices": [
                {
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
async def test_compose_happy_path_returns_messages_and_usage():
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=_ok_composer_response(messages=["Hola, Frank", "¿Te ayudo?"])
    )
    composer = OpenAIComposer(api_key="sk-test")
    out, usage = await composer.compose(
        input=ComposerInput(action="greet", current_stage="greeting", tone=Tone())
    )
    assert out.messages == ["Hola, Frank", "¿Te ayudo?"]
    assert usage is not None
    assert usage.tokens_in == 450
    assert usage.tokens_out == 80
    assert usage.cost_usd == Decimal("0.001925")
    assert usage.fallback_used is False
    assert usage.model == "gpt-4o"


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


@respx.mock
async def test_compose_retries_on_503_then_succeeds():
    route = respx.post("https://api.openai.com/v1/chat/completions").mock(
        side_effect=[Response(503, json={"error": {"message": "boom"}}), _ok_composer_response()]
    )
    composer = OpenAIComposer(api_key="sk-test", retry_delays_ms=(50,))
    _out, usage = await composer.compose(
        input=ComposerInput(action="greet", current_stage="greeting", tone=Tone())
    )
    assert route.call_count == 2
    assert usage is not None
    assert usage.fallback_used is False
    assert usage.cost_usd > Decimal("0")


@respx.mock
async def test_compose_raises_on_exhaustion_without_canned_fallback():
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=Response(503, json={"error": {"message": "down"}})
    )
    composer = OpenAIComposer(api_key="sk-test", retry_delays_ms=(10, 20))
    with pytest.raises(ComposerProviderError) as exc_info:
        await composer.compose(
            input=ComposerInput(action="greet", current_stage="greeting", tone=Tone())
        )
    assert exc_info.value.usage.fallback_used is False
    assert exc_info.value.usage.tokens_in == 0
    assert exc_info.value.usage.cost_usd == Decimal("0")


@pytest.mark.parametrize("status_code", [400, 401, 422])
@respx.mock
async def test_compose_does_not_retry_on_non_retriable(status_code):
    route = respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=Response(status_code, json={"error": {"message": "bad"}})
    )
    composer = OpenAIComposer(api_key="sk-test", retry_delays_ms=(10, 20))
    with pytest.raises(ComposerProviderError) as exc_info:
        await composer.compose(
            input=ComposerInput(action="greet", current_stage="greeting", tone=Tone())
        )
    assert route.call_count == 1
    assert exc_info.value.usage.fallback_used is False


@respx.mock
async def test_compose_treats_malformed_json_as_validation_error():
    bad = Response(
        200,
        json={
            "id": "x",
            "model": "gpt-4o",
            "choices": [
                {
                    "message": {"role": "assistant", "content": '{"messages": []}'},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        },
    )
    route = respx.post("https://api.openai.com/v1/chat/completions").mock(return_value=bad)
    composer = OpenAIComposer(api_key="sk-test", retry_delays_ms=(10, 20))
    with pytest.raises(ComposerProviderError) as exc_info:
        await composer.compose(
            input=ComposerInput(action="greet", current_stage="greeting", tone=Tone())
        )
    assert route.call_count == 1
    assert exc_info.value.usage.fallback_used is False


@respx.mock
async def test_compose_passes_tone_to_prompt():
    route = respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=_ok_composer_response()
    )
    composer = OpenAIComposer(api_key="sk-test")
    await composer.compose(
        input=ComposerInput(
            action="greet",
            current_stage="greeting",
            tone=Tone(
                bot_name="DinamoBot",
                register="informal_mexicano",
                forbidden_phrases=["frase_prohibida_z"],
            ),
        )
    )
    req_body = json.loads(route.calls[0].request.content.decode("utf-8"))
    system = req_body["messages"][0]["content"]
    assert "DinamoBot" in system
    assert "informal_mexicano" in system
    assert "frase_prohibida_z" in system


@respx.mock
async def test_compose_request_uses_max_messages_in_schema():
    route = respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=_ok_composer_response()
    )
    composer = OpenAIComposer(api_key="sk-test")
    await composer.compose(
        input=ComposerInput(action="greet", current_stage="greeting", tone=Tone(), max_messages=3)
    )
    req_body = json.loads(route.calls[0].request.content.decode("utf-8"))
    schema = req_body["response_format"]["json_schema"]["schema"]
    assert schema["properties"]["messages"]["maxItems"] == 3


@respx.mock
async def test_compose_quote_with_no_data_includes_no_inventes():
    from atendia.contracts.flow_mode import FlowMode

    route = respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=_ok_composer_response(messages=["Déjame consultar y te paso el precio."])
    )
    composer = OpenAIComposer(api_key="sk-test")
    await composer.compose(
        input=ComposerInput(
            action="quote",
            flow_mode=FlowMode.SALES,
            action_payload={"status": "no_data", "hint": "catalog not connected"},
            current_stage="quote",
            extracted_data={"interes_producto": "150Z"},
            tone=Tone(),
        )
    )
    req_body = json.loads(route.calls[0].request.content.decode("utf-8"))
    rendered = "\n".join(str(message["content"]) for message in req_body["messages"])
    assert "catalog not connected" in rendered
    assert "150Z" in rendered
