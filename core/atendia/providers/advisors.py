from __future__ import annotations

from typing import Protocol


class AdvisorProvider(Protocol):
    """Provides access to appointment advisors (sales representatives)."""

    async def list_advisors(self) -> list[dict]: ...
    async def get_advisor(self, advisor_id: str) -> dict | None: ...
