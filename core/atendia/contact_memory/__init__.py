from __future__ import annotations

from importlib import import_module
from typing import Any

from atendia.contact_memory.policy import ContactMemoryPolicy
from atendia.contact_memory.schemas import (
    ContactMemoryDecision,
    ContactMemoryPolicyConfig,
    ContactMemoryWriteRequest,
)

__all__ = [
    "ContactMemoryDecision",
    "ContactMemoryPolicy",
    "ContactMemoryPolicyConfig",
    "ContactMemoryService",
    "ContactMemoryWriteRequest",
]


def __getattr__(name: str) -> Any:
    if name != "ContactMemoryService":
        raise AttributeError(f"module 'atendia.contact_memory' has no attribute {name!r}")
    value = getattr(import_module("atendia.contact_memory.service"), name)
    globals()[name] = value
    return value
