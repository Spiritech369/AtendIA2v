"""Structured payload for human_handoffs.payload JSONB."""

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class HandoffReason(str, Enum):
    """Known escalation reasons persisted by the runner."""

    OUTSIDE_24H_WINDOW = "outside_24h_window"
    COMPOSER_FAILED = "composer_failed"
    OBSTACLE_NO_SOLUTION = "obstacle_no_solution"
    USER_SIGNALED_PAPELERIA_COMPLETA = "user_signaled_papeleria_completa"
    PAPELERIA_COMPLETA_FORM_PENDING = "papeleria_completa_form_pending"
    POLICY_NOT_MET = "policy_not_met"
    STAGE_TRIGGERED_HANDOFF = "stage_triggered_handoff"
    DOCS_COMPLETE_FOR_PLAN = "documents_complete_for_selection"
    USER_REQUESTED_HUMAN = "user_requested_human"
    SENSITIVE_PAYMENT_ACCOUNT = "sensitive_payment_account"
    WRONG_ACCOUNT = "wrong_account"


class HandoffSummary(BaseModel):
    """Pre-formatted context for the human agent."""

    reason: HandoffReason
    reason_code: str
    customer: str | None = None
    customer_fields: dict[str, Any] = Field(default_factory=dict)
    docs_recibidos: list[str] = Field(default_factory=list)
    docs_pendientes: list[str] = Field(default_factory=list)
    last_inbound: str
    last_inbound_message: str
    suggested_next_action: str
    funnel_stage: str
    cita_dia: str | None = None
