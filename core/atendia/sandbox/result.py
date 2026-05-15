"""Pure result shapes returned by the sandbox harness (no DB, no logic)."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any


@dataclass
class SandboxTurnResult:
    flow_mode: str | None
    nlu_output: dict[str, Any] | None
    composer_output: dict[str, Any] | None
    would_be_outbound: list[str]
    cost_usd: Decimal
    latency_ms: int | None


@dataclass
class SandboxRunResult:
    turns: list[SandboxTurnResult] = field(default_factory=list)

    @property
    def total_cost_usd(self) -> Decimal:
        return sum((t.cost_usd for t in self.turns), Decimal("0"))
