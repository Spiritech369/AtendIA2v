"""Opt-in pipeline definition for the 'motos crédito' niche (Fase 2).

The neutral starter in ``default_pipeline`` is intentionally vertical-
agnostic (no stages, no doc catalog, no plans) so it works for gyms,
services, B2B, etc. Tenants that sell motos on credit need a richer
default: a 6-stage funnel from lead capture to handoff, a structured
docs catalog, and a `docs_per_plan` map that the `lookup_requirements`
tool reads.

This module ships that richer default WITHOUT mutating
``default_pipeline``. To install it, the operator can:

  1. Copy ``MOTOS_CREDITO_PIPELINE_DEFINITION`` JSON into the Pipeline
     editor's "Import" panel and save (preserves their tenant id).
  2. Run a one-shot seed script that calls ``install_motos_credito``
     against a target tenant_id.

Why a module, not a fixture file? Because the stages, plans, and doc
keys are exercised by tests below — drifting one shape (renaming a
doc key, changing a plan id) without updating the tests would silently
break the contract that the runner / lookup_requirements / evaluator
all depend on.

The plan keys (``nomina_tarjeta_10``, ``nomina_efectivo_20``, ...)
embed BOTH the income source AND the down-payment %, which is how the
NLU prompt's PASO 3 disambiguation funnels customers to a single plan.
The downstream composer (``PLAN MODE PASO 4``) and the
``lookup_requirements`` tool both index off these keys — change one
without updating the others and the bot will hallucinate document
lists for the wrong plan.
"""

from __future__ import annotations

import json
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# ---------------------------------------------------------------------------
# Doc keys — uppercase, prefix DOCS_, used in:
#   - auto_enter_rules conditions (e.g. "DOCS_INE_FRENTE.status = ok")
#   - docs_per_plan lists
#   - documents_catalog entries (label/hint for the UI)
#   - lookup_requirements output (Fase 2)
# Keep them stable; renaming requires a backfill migration on every
# customer.attrs row that already references the old name.
# ---------------------------------------------------------------------------

DOCS_INE_FRENTE = "DOCS_INE_FRENTE"
DOCS_INE_REVERSO = "DOCS_INE_REVERSO"
DOCS_COMPROBANTE_DOMICILIO = "DOCS_COMPROBANTE_DOMICILIO"
DOCS_ESTADOS_CUENTA_NOMINA = "DOCS_ESTADOS_CUENTA_NOMINA"
DOCS_RECIBOS_NOMINA = "DOCS_RECIBOS_NOMINA"
DOCS_CONSTANCIA_SAT = "DOCS_CONSTANCIA_SAT"
DOCS_RECIBO_PENSION = "DOCS_RECIBO_PENSION"


# Plan key → list of required doc keys.
# Reflects the brief's flow: low % down-payment requires stronger
# income proof; sin_comprobantes_25 trades higher down-payment for a
# minimal doc set. Adding a plan = also adding it to the NLU PLAN MODE
# disambiguation tree.
MOTOS_CREDITO_DOCS_PER_PLAN: dict[str, list[str]] = {
    "nomina_tarjeta_10": [
        DOCS_INE_FRENTE,
        DOCS_INE_REVERSO,
        DOCS_COMPROBANTE_DOMICILIO,
        DOCS_ESTADOS_CUENTA_NOMINA,
    ],
    "nomina_efectivo_20": [
        DOCS_INE_FRENTE,
        DOCS_INE_REVERSO,
        DOCS_COMPROBANTE_DOMICILIO,
        DOCS_RECIBOS_NOMINA,
    ],
    "negocio_sat_15": [
        DOCS_INE_FRENTE,
        DOCS_INE_REVERSO,
        DOCS_COMPROBANTE_DOMICILIO,
        DOCS_CONSTANCIA_SAT,
    ],
    "pensionado_imss_15": [
        DOCS_INE_FRENTE,
        DOCS_INE_REVERSO,
        DOCS_COMPROBANTE_DOMICILIO,
        DOCS_RECIBO_PENSION,
    ],
    "sin_comprobantes_25": [
        DOCS_INE_FRENTE,
        DOCS_INE_REVERSO,
        DOCS_COMPROBANTE_DOMICILIO,
    ],
}


# Catalog used by the Pipeline editor and by lookup_requirements to
# render operator-facing labels/hints. Catalog entries are matched to
# docs_per_plan by `key`; entries unused by any plan still appear in
# the editor (operators can manually check them off via the contact panel).
MOTOS_CREDITO_DOCUMENTS_CATALOG: list[dict] = [
    {
        "key": DOCS_INE_FRENTE,
        "label": "INE — frente",
        "hint": "Foto del lado del nombre, las 4 esquinas visibles, sin reflejo.",
    },
    {
        "key": DOCS_INE_REVERSO,
        "label": "INE — reverso",
        "hint": "Foto del lado de la dirección, completa y legible.",
    },
    {
        "key": DOCS_COMPROBANTE_DOMICILIO,
        "label": "Comprobante de domicilio",
        "hint": "Recibo de luz / agua / gas / internet, menor a 2 meses.",
    },
    {
        "key": DOCS_ESTADOS_CUENTA_NOMINA,
        "label": "Estados de cuenta donde se vea la nómina",
        "hint": "Últimos 3 meses con depósitos de tu patrón claramente visibles.",
    },
    {
        "key": DOCS_RECIBOS_NOMINA,
        "label": "Recibos de nómina",
        "hint": "Últimos 3 recibos / talones. Membrete del patrón + firma.",
    },
    {
        "key": DOCS_CONSTANCIA_SAT,
        "label": "Constancia de situación fiscal (SAT)",
        "hint": "Reciente (< 3 meses), del portal del SAT.",
    },
    {
        "key": DOCS_RECIBO_PENSION,
        "label": "Comprobante de pensión IMSS",
        "hint": "Último estado de cuenta de la pensión.",
    },
]


# ---------------------------------------------------------------------------
# Stages — six-stage funnel from the brief. Each carries:
#   - required_fields: drives ask_field (orchestrator + composer PASO X)
#   - auto_enter_rules: deterministic stage entry when a condition matches
#   - is_terminal: blocks auto-backwards moves once reached
# ---------------------------------------------------------------------------

MOTOS_CREDITO_STAGES: list[dict] = [
    {
        "id": "nuevo_lead",
        "label": "Nuevo lead",
        "color": "#6366f1",
        "timeout_hours": 24,
        "required_fields": [],
        "actions_allowed": ["greet", "ask_field", "ask_clarification"],
        # Fase 6 — behavior_mode pins which composer prompt block runs.
        # Nuevo lead → PLAN mode so the bot's PASO 0 hook fires
        # ("Qué bueno que escribes…") instead of generic SUPPORT.
        "behavior_mode": "PLAN",
    },
    {
        "id": "calificacion_inicial",
        "label": "Calificación inicial",
        "color": "#3b82f6",
        "timeout_hours": 48,
        # The bot asks for antigüedad here; cumple_antiguedad gets derived
        # by NLU from "tengo X meses trabajando" (entity → bool).
        "required_fields": [
            {
                "name": "antiguedad_laboral_meses",
                "description": "Cuántos meses lleva en su empleo actual",
            },
        ],
        "actions_allowed": ["ask_field", "lookup_faq", "ask_clarification"],
        "behavior_mode": "PLAN",
        "auto_enter_rules": {
            "enabled": True,
            "match": "all",
            "conditions": [
                {"field": "cumple_antiguedad", "operator": "equals", "value": True},
            ],
        },
    },
    {
        "id": "plan_seleccionado",
        "label": "Plan seleccionado",
        "color": "#0ea5e9",
        "timeout_hours": 48,
        "required_fields": [
            {"name": "tipo_credito", "description": "Tipo de comprobación de ingresos"},
            {"name": "plan_credito", "description": "Plan + porcentaje de enganche"},
        ],
        "actions_allowed": ["ask_field", "lookup_faq"],
        "behavior_mode": "PLAN",
        "auto_enter_rules": {
            "enabled": True,
            "match": "all",
            "conditions": [
                {"field": "plan_credito", "operator": "exists"},
            ],
        },
    },
    {
        "id": "papeleria_incompleta",
        "label": "Papelería incompleta",
        "color": "#f59e0b",
        "timeout_hours": 72,
        "actions_allowed": ["ask_field", "lookup_faq"],
        # Doc collection — pin DOC mode so the composer reuses
        # quality-check phrasing instead of switching to PLAN/SALES
        # when the user asks "¿qué precio tiene la moto?".
        "behavior_mode": "DOC",
        # Enter the moment ANY credit doc field appears on the customer.
        # The runner will sit here until docs_complete_for_plan flips true.
        "auto_enter_rules": {
            "enabled": True,
            "match": "any",
            "conditions": [
                {"field": f"{k}.status", "operator": "equals", "value": "ok"}
                for k in [
                    DOCS_INE_FRENTE,
                    DOCS_INE_REVERSO,
                    DOCS_COMPROBANTE_DOMICILIO,
                    DOCS_ESTADOS_CUENTA_NOMINA,
                    DOCS_RECIBOS_NOMINA,
                    DOCS_CONSTANCIA_SAT,
                    DOCS_RECIBO_PENSION,
                ]
            ],
        },
    },
    {
        "id": "papeleria_completa",
        "label": "Papelería completa",
        "color": "#10b981",
        # Fase 4 — when the customer's `docs_complete_for_plan` flips
        # true and this stage auto-enters, the runner pauses the bot,
        # persists a `human_handoffs` row with summary, and emits the
        # BOT_PAUSED / HUMAN_HANDOFF_REQUESTED / DOCS_COMPLETE_FOR_PLAN
        # system events. The operator picks up from here — Composer
        # does NOT reply automatically on this transition turn.
        "pause_bot_on_enter": True,
        "handoff_reason": "docs_complete_for_plan",
        "actions_allowed": ["escalate_to_human", "ask_clarification"],
        "auto_enter_rules": {
            "enabled": True,
            "match": "all",
            "conditions": [
                {"field": "plan_credito", "operator": "docs_complete_for_plan"},
            ],
        },
    },
    {
        "id": "revision_humana",
        "label": "Revisión humana",
        "color": "#22c55e",
        "is_terminal": True,
        "actions_allowed": ["escalate_to_human"],
    },
]


# ---------------------------------------------------------------------------
# Full pipeline definition. Shape matches PipelineDefinition Pydantic
# model — validated by the unit test below.
# ---------------------------------------------------------------------------

# Fase 3 — when Vision classifies an image as one of these categories,
# the runner writes `customer.attrs[DOCS_X] = {status, ...}` for the
# listed DOCS_* keys. The INE entry is the only multi-side doc: when
# Vision reports `quality_check.side == "front"` we write only the
# first key; `"back"` writes the second; `"unknown"` + `metadata.ambos_lados=true`
# writes both. See `apply_vision_to_attrs._decide_doc_keys` for the
# full disambiguation.
MOTOS_CREDITO_VISION_DOC_MAPPING: dict[str, list[str]] = {
    "ine": [DOCS_INE_FRENTE, DOCS_INE_REVERSO],
    "comprobante": [DOCS_COMPROBANTE_DOMICILIO],
    "estado_cuenta": [DOCS_ESTADOS_CUENTA_NOMINA],
    "recibo_nomina": [DOCS_RECIBOS_NOMINA],
    "constancia_sat": [DOCS_CONSTANCIA_SAT],
    "imss": [DOCS_RECIBO_PENSION],
    # `factura` is intentionally absent — moto invoices aren't part of
    # the customer's credit file in this seed; tenants who collect them
    # can add the mapping in the pipeline editor.
}


MOTOS_CREDITO_PIPELINE_DEFINITION: dict = {
    "version": 1,
    "stages": MOTOS_CREDITO_STAGES,
    "fallback": "ask_clarification",
    "nlu": {"history_turns": 3},
    "composer": {"history_turns": 3},
    "flow_mode_rules": [],
    "docs_per_plan": MOTOS_CREDITO_DOCS_PER_PLAN,
    "documents_catalog": MOTOS_CREDITO_DOCUMENTS_CATALOG,
    "vision_doc_mapping": MOTOS_CREDITO_VISION_DOC_MAPPING,
}


async def install_motos_credito_pipeline(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    overwrite: bool = False,
) -> bool:
    """Install the motos-crédito pipeline for a tenant.

    By default, NOOPs when the tenant already has an active pipeline —
    operators who customised the starter shouldn't get their work wiped
    by a one-shot script. Pass ``overwrite=True`` to deactivate the
    existing active row and install version+1 alongside it.

    Returns True on install, False on noop. Idempotent on overwrite=False;
    idempotent under overwrite=True only at the tenant_id level (calling
    twice produces version v+2 / v+3 / ... but the active row is always
    the latest motos definition).
    """
    existing_active = (
        await session.execute(
            text(
                "SELECT version FROM tenant_pipelines "
                "WHERE tenant_id = :t AND active = true "
                "ORDER BY version DESC LIMIT 1"
            ),
            {"t": tenant_id},
        )
    ).scalar_one_or_none()

    if existing_active is not None and not overwrite:
        return False

    new_version = int(existing_active or 0) + 1
    if existing_active is not None:
        await session.execute(
            text(
                "UPDATE tenant_pipelines SET active = false WHERE tenant_id = :t AND active = true"
            ),
            {"t": tenant_id},
        )

    await session.execute(
        text(
            "INSERT INTO tenant_pipelines "
            "(tenant_id, version, definition, active) "
            "VALUES (:t, :v, CAST(:def AS jsonb), true)"
        ),
        {
            "t": tenant_id,
            "v": new_version,
            "def": json.dumps(MOTOS_CREDITO_PIPELINE_DEFINITION),
        },
    )
    return True
