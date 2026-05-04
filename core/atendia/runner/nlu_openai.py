"""OpenAI gpt-4o-mini classifier with structured outputs.

T15 implements only the happy path. T16+ adds retries and error handling.
"""
import time

from openai import AsyncOpenAI

from atendia.contracts.nlu_result import NLUResult
from atendia.contracts.pipeline_definition import FieldSpec
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


def _build_json_schema() -> dict:
    """Strict JSON schema for OpenAI structured outputs.

    OpenAI requires:
    - additionalProperties: false on every object.
    - required must list every property key.
    - every leaf must declare a type (no untyped Any).
    """
    schema = NLUResult.model_json_schema()

    def _walk(node):
        if isinstance(node, dict):
            # Patch untyped properties (e.g., ExtractedField.value: Any)
            props = node.get("properties")
            if isinstance(props, dict):
                for k, v in list(props.items()):
                    if isinstance(v, dict) and not _is_typed(v):
                        # Preserve title if present, replace body with the union
                        title = v.get("title")
                        replacement = dict(_ANY_VALUE_SCHEMA)
                        if title:
                            replacement["title"] = title
                        props[k] = replacement
            # Strict-mode object hygiene
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


_NLU_JSON_SCHEMA = _build_json_schema()


class OpenAINLU:
    """gpt-4o-mini classifier with structured outputs (no retry yet — T16)."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "gpt-4o-mini",
        timeout_s: float = 8.0,
    ) -> None:
        self._client = AsyncOpenAI(api_key=api_key, max_retries=0, timeout=timeout_s)
        self._model = model

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
        t0 = time.perf_counter()
        resp = await self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            response_format={"type": "json_schema", "json_schema": _NLU_JSON_SCHEMA},
            temperature=0,
        )
        result = NLUResult.model_validate_json(resp.choices[0].message.content)
        usage = UsageMetadata(
            model=resp.model,
            tokens_in=resp.usage.prompt_tokens,
            tokens_out=resp.usage.completion_tokens,
            cost_usd=compute_cost(
                resp.model, resp.usage.prompt_tokens, resp.usage.completion_tokens
            ),
            latency_ms=int((time.perf_counter() - t0) * 1000),
        )
        return result, usage
