from __future__ import annotations

from atendia.contracts.pipeline_definition import FieldSpec
from atendia.runner.nlu_protocol import NLUProvider, UsageMetadata


def _is_provider_error(usage: UsageMetadata | None) -> bool:
    return bool(usage and usage.error_type)


class FallbackNLU:
    def __init__(self, primary: NLUProvider, fallback: NLUProvider) -> None:
        self.primary = primary
        self.fallback = fallback

    async def classify(
        self,
        *,
        text: str,
        current_stage: str,
        required_fields: list[FieldSpec],
        optional_fields: list[FieldSpec],
        history: list[tuple[str, str]],
    ):
        result, usage = await self.primary.classify(
            text=text,
            current_stage=current_stage,
            required_fields=required_fields,
            optional_fields=optional_fields,
            history=history,
        )
        if not _is_provider_error(usage):
            return result, usage

        fallback_result, fallback_usage = await self.fallback.classify(
            text=text,
            current_stage=current_stage,
            required_fields=required_fields,
            optional_fields=optional_fields,
            history=history,
        )
        if fallback_usage is not None:
            fallback_usage.fallback_used = True
        return fallback_result, fallback_usage
