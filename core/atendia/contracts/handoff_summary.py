"""Structured payload for human_handoffs.payload JSONB (Phase 3c.2).

V1 prompt requires "Before assigning to @Francisco Esparza in ANY
scenario, ALWAYS add internal comment". This contract makes that
comment a typed payload instead of free text.
"""

from enum import Enum

from pydantic import BaseModel


class HandoffReason(str, Enum):
    """Por qué se escaló a humano.

    Status of each value (Sprint C.9 audit, 2026-05-14):

    Wired end-to-end (runner reads this reason and persists a handoff):
    * ``OUTSIDE_24H_WINDOW`` — runner check (conversation_runner.py:904)
    * ``COMPOSER_FAILED`` — runner catch-all (conversation_runner.py:972)
    * ``STAGE_TRIGGERED_HANDOFF`` — pause_bot_on_enter stages
      (conversation_runner.py:1173)
    * ``DOCS_COMPLETE_FOR_PLAN`` — runner derived from stage transition

    **Forward-contract only** (composer prompts ask gpt-4o to emit them
    as ``suggested_handoff="..."``, but the runner does NOT read that
    field today — so an escalation hinted by the LLM is silently dropped):

    * ``OBSTACLE_NO_SOLUTION`` — prompted in composer_prompts.py:217,225
    * ``USER_SIGNALED_PAPELERIA_COMPLETA`` — not yet prompted
    * ``PAPELERIA_COMPLETA_FORM_PENDING`` — not yet prompted
    * ``ANTIGUEDAD_LT_6M`` — prompted in composer_prompts.py:77

    Closing this gap requires three changes (~1 session):
    1. Add ``suggested_handoff: str | None`` to ``ComposerOutput``
       (atendia/runner/composer_protocol.py) and to ``_composer_schema``
       (atendia/runner/composer_openai.py).
    2. Update the prompts so gpt-4o emits the field in its JSON
       (already textually instructed; needs to be in the schema's
       ``required`` for OpenAI strict mode, with ``["null","string"]``).
    3. After ``runner.compose()`` returns, check
       ``output.suggested_handoff``; if it matches one of these values,
       call ``persist_handoff(reason=HandoffReason(value))`` and skip
       the rest of the turn.

    Tracked in the decision matrix as item C.9.
    """

    OUTSIDE_24H_WINDOW = "outside_24h_window"
    COMPOSER_FAILED = "composer_failed"
    OBSTACLE_NO_SOLUTION = "obstacle_no_solution"
    USER_SIGNALED_PAPELERIA_COMPLETA = "user_signaled_papeleria_completa"
    PAPELERIA_COMPLETA_FORM_PENDING = "papeleria_completa_form_pending"
    ANTIGUEDAD_LT_6M = "antiguedad_lt_6m"
    # Fase 4 — fired when the conversation enters a stage whose
    # `pause_bot_on_enter=true`. The runner derives the reason from
    # `stage.handoff_reason` (when set) or falls back to this generic.
    STAGE_TRIGGERED_HANDOFF = "stage_triggered_handoff"
    DOCS_COMPLETE_FOR_PLAN = "docs_complete_for_plan"


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
