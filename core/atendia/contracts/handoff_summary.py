"""Structured payload for human_handoffs.payload JSONB (Phase 3c.2).

V1 prompt requires "Before assigning to @Francisco Esparza in ANY
scenario, ALWAYS add internal comment". This contract makes that
comment a typed payload instead of free text.
"""
from enum import Enum

from pydantic import BaseModel


class HandoffReason(str, Enum):
    """Por qué se escaló a humano."""

    OUTSIDE_24H_WINDOW = "outside_24h_window"
    COMPOSER_FAILED = "composer_failed"
    OBSTACLE_NO_SOLUTION = "obstacle_no_solution"
    USER_SIGNALED_PAPELERIA_COMPLETA = "user_signaled_papeleria_completa"
    PAPELERIA_COMPLETA_FORM_PENDING = "papeleria_completa_form_pending"
    ANTIGUEDAD_LT_6M = "antiguedad_lt_6m"


class HandoffSummary(BaseModel):
    """Pre-formatted context for the human agent.

    Persisted in human_handoffs.payload (JSONB column already exists
    from Phase 1). Frontend (Phase 4) renders this verbatim.
    """

    reason: HandoffReason
    nombre: str | None = None
    modelo_moto: str | None = None
    plan_credito: str | None = None
    enganche_estimado: str | None = None
    docs_recibidos: list[str] = []
    docs_pendientes: list[str] = []
    last_inbound_message: str
    suggested_next_action: str
    funnel_stage: str
    cita_dia: str | None = None
