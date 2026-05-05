"""OpenAI Composer (gpt-4o) with strict structured outputs and retry."""
import asyncio
import json
import time
from decimal import Decimal

from openai import AsyncOpenAI

from atendia.runner._openai_errors import _NON_RETRIABLE, _RETRIABLE
from atendia.runner.composer_canned import CannedComposer
from atendia.runner.composer_prompts import build_composer_prompt
from atendia.runner.composer_protocol import (
    ComposerInput,
    ComposerOutput,
    ComposerProvider,
    UsageMetadata,
)
from atendia.runner.nlu.pricing import compute_cost


def _composer_schema(max_messages: int) -> dict:
    """Strict-mode-compliant JSON schema for ComposerOutput."""
    return {
        "name": "composer_output",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "messages": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                    "maxItems": max_messages,
                },
            },
            "required": ["messages"],
            "additionalProperties": False,
        },
    }


class OpenAIComposer:
    """gpt-4o classifier with strict structured outputs, retry + canned fallback."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "gpt-4o",
        timeout_s: float = 8.0,
        retry_delays_ms: tuple[int, ...] = (500, 2000),
        fallback: ComposerProvider | None = None,
    ) -> None:
        self._client = AsyncOpenAI(api_key=api_key, max_retries=0, timeout=timeout_s)
        self._model = model
        self._delays = (0, *retry_delays_ms)
        self._fallback = fallback or CannedComposer()

    async def compose(
        self, *, input: ComposerInput,
    ) -> tuple[ComposerOutput, UsageMetadata | None]:
        messages = build_composer_prompt(input)
        json_schema = _composer_schema(input.max_messages)
        t0 = time.perf_counter()

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
                output = ComposerOutput.model_validate(raw)
                usage = UsageMetadata(
                    model=resp.model,
                    tokens_in=resp.usage.prompt_tokens,
                    tokens_out=resp.usage.completion_tokens,
                    cost_usd=compute_cost(
                        resp.model, resp.usage.prompt_tokens, resp.usage.completion_tokens,
                    ),
                    latency_ms=int((time.perf_counter() - t0) * 1000),
                    fallback_used=False,
                )
                return output, usage
            except _RETRIABLE:
                continue
            except _NON_RETRIABLE:
                break

        # Exhausted or non-retriable: fall back to canned, signal via fallback_used.
        canned_output, _ = await self._fallback.compose(input=input)
        usage = UsageMetadata(
            model=self._model,
            tokens_in=0,
            tokens_out=0,
            cost_usd=Decimal("0"),
            latency_ms=int((time.perf_counter() - t0) * 1000),
            fallback_used=True,
        )
        return canned_output, usage
