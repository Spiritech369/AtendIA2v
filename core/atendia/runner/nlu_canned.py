"""Fixture-driven NLU for deterministic tests.

Reads a list of pre-built NLUResult from a YAML file and returns them in order
regardless of the actual input. Returns UsageMetadata=None — there's no LLM call.
"""
from pathlib import Path

import yaml

from atendia.contracts.nlu_result import NLUResult
from atendia.contracts.pipeline_definition import FieldSpec
from atendia.runner.nlu_protocol import UsageMetadata


class CannedNLU:
    def __init__(self, fixture_path: Path) -> None:
        data = yaml.safe_load(fixture_path.read_text(encoding="utf-8"))
        self._queue = [NLUResult.model_validate(item) for item in data["nlu_results"]]
        self._idx = 0

    async def classify(
        self,
        *,
        text: str,
        current_stage: str,
        required_fields: list[FieldSpec],
        optional_fields: list[FieldSpec],
        history: list[tuple[str, str]],
    ) -> tuple[NLUResult, UsageMetadata | None]:
        if self._idx >= len(self._queue):
            raise IndexError("no more canned NLU results")
        result = self._queue[self._idx]
        self._idx += 1
        return result, None
