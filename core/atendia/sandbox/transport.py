"""Side-effect-free arq pool: records would-be jobs, dispatches none."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class _CapturedJob:
    def __init__(self, function: str) -> None:
        self.function = function


@dataclass
class CapturingArqPool:
    captured: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = field(default_factory=list)

    @property
    def send_count(self) -> int:
        return 0

    async def enqueue_job(self, function: str, *args: Any, **kwargs: Any) -> _CapturedJob:
        self.captured.append((function, args, kwargs))
        return _CapturedJob(function)

    async def aclose(self) -> None:  # mirrors ArqRedis API used by callers
        return None
