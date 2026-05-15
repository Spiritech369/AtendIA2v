"""FlowMode — uno de los 6 modos del v1 prompt.

Decidido por el router determinístico cada turno. Determina cuál
de los 6 prompts del composer se usa.
"""

from enum import Enum


class FlowMode(str, Enum):
    """Los 6 modos conversacionales del v1 prompt."""

    PLAN = "PLAN"
    SALES = "SALES"
    DOC = "DOC"
    OBSTACLE = "OBSTACLE"
    RETENTION = "RETENTION"
    SUPPORT = "SUPPORT"
