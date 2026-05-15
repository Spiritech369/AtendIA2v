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


class CostCapExceeded(Exception):  # noqa: N818 — deliberate API name fixed by the harness plan (imported by A4/A3/P2)
    """Raised when a sandboxed conversation's running cost exceeds the cap.

    Carries the turns completed so far — *including* the turn that tripped
    the cap (it ran, so its cost is real) — and the total spent, so the
    caller can show partial progress instead of losing it.
    """

    def __init__(self, *, partial: list[SandboxTurnResult], spent: Decimal) -> None:
        self.partial = partial
        self.spent = spent
        super().__init__(
            f"sandbox cost cap exceeded: spent {spent} USD over {len(partial)} turn(s)"
        )
