"""OpenAI gpt-4o-mini classifier with structured outputs.

T15: happy path. T16+: retries and error handling.
"""
import asyncio
import json
import time
from decimal import Decimal

from openai import AsyncOpenAI

from atendia.contracts.nlu_result import Intent, NLUResult, Sentiment
from atendia.contracts.pipeline_definition import FieldSpec
from atendia.runner._openai_errors import _NON_RETRIABLE, _RETRIABLE
from atendia.runner.nlu.pricing import compute_cost
from atendia.runner.nlu_prompts import build_prompt
from atendia.runner.nlu_protocol import UsageMetadata

_ANY_VALUE_SCHEMA = {
    "anyOf": [
        {"type": "string"},
        {"type": "number"},
        {"type": "integer"},
        {"type": "boolean"},
        {"type": "null"},
    ]
}


def _is_typed(node: dict) -> bool:
    """Return True if a property schema declares a type or a discriminator."""
    return any(k in node for k in ("type", "$ref", "anyOf", "oneOf", "allOf", "enum"))


def _entities_schema(field_names: list[str]) -> dict:
    """Build the strict-mode-compliant `entities` object schema.

    OpenAI strict mode rejects open-ended `additionalProperties: <schema>`.
    We list every extractable field by name; each is `anyOf [ExtractedField, null]`
    so the LLM can omit a value while still satisfying `required`.
    """
    return {
        "type": "object",
        "properties": {
            name: {"anyOf": [{"$ref": "#/$defs/ExtractedField"}, {"type": "null"}]}
            for name in field_names
        },
        "required": list(field_names),
        "additionalProperties": False,
    }


def _build_strict_schema(field_names: list[str]) -> dict:
    """Generate a per-call JSON schema for OpenAI strict structured outputs.

    The returned dict is the value of `response_format.json_schema`.
    """
    schema = NLUResult.model_json_schema()

    # Override `entities` with a strict-mode-compatible explicit object.
    schema["properties"]["entities"] = _entities_schema(field_names)

    def _walk(node):
        if isinstance(node, dict):
            props = node.get("properties")
            if isinstance(props, dict):
                for k, v in list(props.items()):
                    if isinstance(v, dict) and not _is_typed(v):
                        title = v.get("title")
                        replacement = dict(_ANY_VALUE_SCHEMA)
                        if title:
                            replacement["title"] = title
                        props[k] = replacement
            if node.get("type") == "object":
                node["additionalProperties"] = False
                if isinstance(props, dict):
                    node["required"] = list(props.keys())
            for v in node.values():
                _walk(v)
        elif isinstance(node, list):
            for v in node:
                _walk(v)

    _walk(schema)
    return {"name": "nlu_result", "strict": True, "schema": schema}


class OpenAINLU:
    """gpt-4o-mini classifier with strict structured outputs and retry."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "gpt-4o-mini",
        timeout_s: float = 8.0,
        retry_delays_ms: tuple[int, ...] = (500, 2000),
    ) -> None:
        self._client = AsyncOpenAI(api_key=api_key, max_retries=0, timeout=timeout_s)
        self._model = model
        self._delays = (0, *retry_delays_ms)

    async def classify(
        self,
        *,
        text: str,
        current_stage: str,
        required_fields: list[FieldSpec],
        optional_fields: list[FieldSpec],
        history: list[tuple[str, str]],
    ) -> tuple[NLUResult, UsageMetadata | None]:
        messages = build_prompt(
            text=text,
            current_stage=current_stage,
            required_fields=required_fields,
            optional_fields=optional_fields,
            history=history,
        )
        field_names = [f.name for f in required_fields] + [f.name for f in optional_fields]
        json_schema = _build_strict_schema(field_names)

        t0 = time.perf_counter()
        last_exc: Exception | None = None

        for delay_ms in self._delays:
            if delay_ms:
                await asyncio.sleep(delay_ms / 1000)
            try:
                resp = await self._client.chat.completions.create(  # type: ignore[call-overload]
                    model=self._model,
                    messages=messages,
                    response_format={"type": "json_schema", "json_schema": json_schema},
                    temperature=0,
                )
                raw = json.loads(resp.choices[0].message.content)
                # OpenAI strict mode requires every entity field as a key with anyOf [..., null].
                # Drop nulls before validating against the narrower NLUResult contract.
                if isinstance(raw.get("entities"), dict):
                    raw["entities"] = {k: v for k, v in raw["entities"].items() if v is not None}
                result = NLUResult.model_validate(raw)
                usage = UsageMetadata(
                    model=resp.model,
                    tokens_in=resp.usage.prompt_tokens,
                    tokens_out=resp.usage.completion_tokens,
                    cost_usd=compute_cost(
                        resp.model, resp.usage.prompt_tokens, resp.usage.completion_tokens,
                    ),
                    latency_ms=int((time.perf_counter() - t0) * 1000),
                )
                return result, usage
            except _RETRIABLE as e:
                last_exc = e
                continue
            except _NON_RETRIABLE as e:
                last_exc = e
                break

        return self._error_result(last_exc), self._zero_usage(t0)

    def _error_result(self, exc: Exception | None) -> NLUResult:
        name = type(exc).__name__ if exc else "Unknown"
        return NLUResult(
            intent=Intent.UNCLEAR,
            entities={},
            sentiment=Sentiment.NEUTRAL,
            confidence=0.0,
            ambiguities=[f"nlu_error:{name}"],
        )

    def _zero_usage(self, t0: float) -> UsageMetadata:
        return UsageMetadata(
            model=self._model,
            tokens_in=0,
            tokens_out=0,
            cost_usd=Decimal("0"),
            latency_ms=int((time.perf_counter() - t0) * 1000),
        )
