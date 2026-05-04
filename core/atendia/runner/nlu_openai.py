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


def _build_json_schema() -> dict:
    """Strict JSON schema for OpenAI structured outputs.

    OpenAI requires `additionalProperties: false` on every nested object.
    Pydantic doesn't add it by default, so we recurse and inject it.
    """
    schema = NLUResult.model_json_schema()

    def _walk(node):
        if isinstance(node, dict):
            if node.get("type") == "object":
                node.setdefault("additionalProperties", False)
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
