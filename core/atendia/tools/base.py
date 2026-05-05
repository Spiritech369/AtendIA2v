from abc import ABC, abstractmethod
from typing import Any, Literal

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession


class ToolNotFoundError(Exception):
    """Raised when a tool name is not in the registry."""


class Tool(ABC):
    name: str

    @abstractmethod
    async def run(self, session: AsyncSession, **kwargs: Any) -> dict:
        ...


class ToolNoDataResult(BaseModel):
    """Returned (or constructed) when a tool can't produce real data yet.

    Used by Phase 3b's Composer pathway for actions like `quote` / `lookup_faq` /
    `search_catalog` when the tenant catalog or FAQs are not populated. The
    Composer's prompt receives `hint` and is instructed to redirect rather than
    invent data.

    Phase 3c will populate the catalog/FAQs and tools will start returning real
    data; ToolNoDataResult will become the rare error path then.
    """
    status: Literal["no_data"] = "no_data"
    hint: str
