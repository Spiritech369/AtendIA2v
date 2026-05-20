from __future__ import annotations

import json
import time
from decimal import Decimal

from anthropic import APIConnectionError, APIStatusError, APITimeoutError, AsyncAnthropic

from atendia.contracts.nlu_result import Intent, NLUResult, Sentiment
from atendia.contracts.pipeline_definition import FieldSpec
from atendia.runner.nlu.pricing import compute_cost
from atendia.runner.nlu_prompts import build_prompt
from atendia.runner.nlu_protocol import UsageMetadata


class AnthropicHaikuNLU:
    def __init__(
        self,
        *,
        api_key: str,
        model: str = "claude-haiku-4-5-20251001",
        timeout_s: float = 8.0,
        topics: list[dict] | None = None,
    ) -> None:
        self._client = AsyncAnthropic(api_key=api_key, timeout=timeout_s, max_retries=0)
        self._model = model
        self._topics = topics or []

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
            topics=self._topics,
        )
        system = messages[0]["content"]
        anthropic_messages = [
            {
                "role": "user" if message["role"] == "user" else "assistant",
                "content": message["content"],
            }
            for message in messages[1:]
        ]

        t0 = time.perf_counter()
        try:
            resp = await self._client.messages.create(
                model=self._model,
                max_tokens=1000,
                temperature=0,
                system=f"{system}\n\nDevuelve solo JSON valido, sin markdown, sin texto extra.",
                messages=anthropic_messages,
            )
            raw_text = "".join(
                block.text for block in resp.content if getattr(block, "type", None) == "text"
            )
            result = NLUResult.model_validate(json.loads(raw_text))
            usage = UsageMetadata(
                model=resp.model,
                tokens_in=resp.usage.input_tokens,
                tokens_out=resp.usage.output_tokens,
                cost_usd=compute_cost(
                    resp.model,
                    resp.usage.input_tokens,
                    resp.usage.output_tokens,
                ),
                latency_ms=int((time.perf_counter() - t0) * 1000),
            )
            return result, usage
        except (APIConnectionError, APIStatusError, APITimeoutError, json.JSONDecodeError) as exc:
            return self._error_result(exc), self._zero_usage(t0, exc)

    def _error_result(self, exc: Exception | None) -> NLUResult:
        name = type(exc).__name__ if exc else "Unknown"
        return NLUResult(
            intent=Intent.UNCLEAR,
            topic=None,
            sub_intent=None,
            sales_signal="none",
            entities={},
            sentiment=Sentiment.NEUTRAL,
            confidence=0.0,
            ambiguities=[f"nlu_error:{name}"],
        )

    def _zero_usage(self, t0: float, exc: Exception | None = None) -> UsageMetadata:
        return UsageMetadata(
            model=self._model,
            tokens_in=0,
            tokens_out=0,
            cost_usd=Decimal("0"),
            latency_ms=int((time.perf_counter() - t0) * 1000),
            error_type=type(exc).__name__ if exc else None,
        )
