from abc import ABC, abstractmethod
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession


class ToolNotFoundError(Exception):
    """Raised when a tool name is not in the registry."""


class Tool(ABC):
    name: str

    @abstractmethod
    async def run(self, session: AsyncSession, **kwargs: Any) -> dict:
        ...
