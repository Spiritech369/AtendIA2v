"""Common interface for NLU providers.

Three implementations live in this package:
- OpenAINLU      — real LLM, used in production (T15+)
- KeywordNLU     — keyword-based fallback for dev/tests
- CannedNLU      — fixture-driven for deterministic tests

All return (NLUResult, UsageMetadata | None). Mocks/fakes return None.
"""

from decimal import Decimal
from typing import Protocol

from pydantic import BaseModel, Field

from atendia.contracts.nlu_result import NLUResult
from atendia.contracts.pipeline_definition import FieldSpec


class UsageMetadata(BaseModel):
    model: str
    tokens_in: int = Field(ge=0)
    tokens_out: int = Field(ge=0)
    cost_usd: Decimal = Field(ge=0)
    latency_ms: int = Field(ge=0)
    fallback_used: bool = False


class NLUProvider(Protocol):
    async def classify(
        self,
        *,
        text: str,
        current_stage: str,
        required_fields: list[FieldSpec],
        optional_fields: list[FieldSpec],
        history: list[tuple[str, str]],
    ) -> tuple[NLUResult, UsageMetadata | None]: ...
