"""Pure functions that derive flow signals from ExtractedFields.

No DB, no LLM. The runner calls these on every turn to decide what
the bot should do next.
"""
from atendia.contracts.extracted_fields import ExtractedFields, PlanCredito


def funnel_stage(extracted: ExtractedFields) -> str:
    """Where the customer is in the sales funnel.

    Returns one of {"plan", "sales", "doc", "close"}, derived purely
    from which fields are populated. Order of precedence (top-down):
      close > doc > sales > plan.

    `funnel_stage` is NOT persisted — it's recomputed whenever needed
    (composer prompts, analytics, handoff summaries).
    """
    if extracted.papeleria_completa:
        return "close"
    if extracted.modelo_moto:
        return "doc"
    if extracted.plan_credito:
        return "sales"
    return "plan"


def next_pending_doc(
    extracted: ExtractedFields,
    plan_credito: PlanCredito | None,
    docs_per_plan: dict[str, list[str]],
) -> str | None:
    """First document in priority order that hasn't been received.

    `docs_per_plan` is a dict mapping plan label (e.g. "Nómina Tarjeta")
    to the ordered list of required doc keys. Configurable per tenant
    via `tenant_pipelines.definition.docs_per_plan` JSONB.

    Returns None when no plan is assigned (we don't know what to ask
    yet) OR when all required docs have been received (papelería
    completa).
    """
    if plan_credito is None:
        return None
    for plan_label, required_docs in docs_per_plan.items():
        if not _plan_label_matches(plan_label, plan_credito, extracted):
            continue
        for doc in required_docs:
            if not getattr(extracted, f"docs_{doc}", False):
                return doc
        return None
    return None


def _plan_label_matches(
    plan_label: str,
    plan_credito: PlanCredito,
    extracted: ExtractedFields,
) -> bool:
    """Plans are identified by tipo_credito (5 labels), not plan_credito
    percentage (3 labels). The label match uses tipo_credito if set;
    otherwise we can't disambiguate."""
    if extracted.tipo_credito is None:
        return False
    return plan_label == extracted.tipo_credito.value
