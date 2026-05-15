"""Helpers derivados sobre ExtractedFields (Phase 3c.2).

funnel_stage() y next_pending_doc() son funciones puras, sin DB.
Toda la lógica de "dónde está el cliente" se deriva del estado
extraído — no se persiste por separado.
"""

from atendia.contracts.extracted_fields import (
    ExtractedFields,
    PlanCredito,
    TipoCredito,
)
from atendia.state_machine.derived import funnel_stage, next_pending_doc

# Catálogo de docs requeridos por plan (debería vivir en pipeline JSONB
# en runtime; aquí lo hardcodeamos para los tests).
_DOCS_PER_PLAN = {
    "Nómina Tarjeta": ["ine", "comprobante", "estados_de_cuenta", "nomina"],
    "Nómina Recibos": ["ine", "comprobante", "nomina"],
    "Pensionados": ["ine", "comprobante", "estados_de_cuenta", "imss"],
    "Negocio SAT": ["ine", "comprobante", "estados_de_cuenta", "constancia_sat", "factura"],
    "Sin Comprobantes": ["ine", "comprobante"],
}


# ----- funnel_stage --------------------------------------------------


def test_funnel_stage_plan_when_no_plan_credito() -> None:
    """Cliente nuevo sin plan asignado → stage = plan."""
    s = ExtractedFields()
    assert funnel_stage(s) == "plan"


def test_funnel_stage_sales_when_plan_assigned() -> None:
    """Tiene plan_credito pero no modelo_moto → sales."""
    s = ExtractedFields(plan_credito=PlanCredito.PLAN_10)
    assert funnel_stage(s) == "sales"


def test_funnel_stage_doc_when_modelo_moto_set() -> None:
    """Tiene modelo_moto → ya cotizó → doc (recolectando papeles)."""
    s = ExtractedFields(plan_credito=PlanCredito.PLAN_10, modelo_moto="Adventure")
    assert funnel_stage(s) == "doc"


def test_funnel_stage_close_when_papeleria_completa() -> None:
    """Papelería lista → close (form de cierre)."""
    s = ExtractedFields(
        plan_credito=PlanCredito.PLAN_10,
        modelo_moto="Adventure",
        papeleria_completa=True,
    )
    assert funnel_stage(s) == "close"


def test_funnel_stage_orden_de_precedencia_es_top_down() -> None:
    """Si papeleria_completa=true pero modelo_moto está vacío, sigue close.
    El orden de los if's: close > doc > sales > plan."""
    s = ExtractedFields(papeleria_completa=True)
    assert funnel_stage(s) == "close"


# ----- next_pending_doc ----------------------------------------------


def test_next_pending_doc_none_when_plan_not_assigned() -> None:
    """Sin plan_credito no sabemos qué pedir."""
    s = ExtractedFields()
    assert next_pending_doc(s, None, _DOCS_PER_PLAN) is None


def test_next_pending_doc_returns_first_missing() -> None:
    """Primer doc en orden de prioridad que aún no se ha recibido."""
    s = ExtractedFields(
        plan_credito=PlanCredito.PLAN_10,
        tipo_credito=TipoCredito.NOMINA_TARJETA,
    )
    # Plan 10% (Nómina Tarjeta) requiere INE, comprobante, estados, nomina
    assert next_pending_doc(s, PlanCredito.PLAN_10, _DOCS_PER_PLAN) == "ine"


def test_next_pending_doc_skips_received() -> None:
    """Salta docs ya recibidos."""
    s = ExtractedFields(
        plan_credito=PlanCredito.PLAN_10,
        tipo_credito=TipoCredito.NOMINA_TARJETA,
        docs_ine=True,
    )
    assert next_pending_doc(s, PlanCredito.PLAN_10, _DOCS_PER_PLAN) == "comprobante"


def test_next_pending_doc_handles_out_of_order_receipt() -> None:
    """Cliente mandó comprobante antes que INE → siguiente sigue siendo INE."""
    s = ExtractedFields(
        plan_credito=PlanCredito.PLAN_10,
        tipo_credito=TipoCredito.NOMINA_TARJETA,
        docs_comprobante=True,  # llegó fuera de orden
    )
    assert next_pending_doc(s, PlanCredito.PLAN_10, _DOCS_PER_PLAN) == "ine"


def test_next_pending_doc_returns_none_when_papeleria_completa() -> None:
    """Todos los docs requeridos del plan recibidos → None."""
    s = ExtractedFields(
        plan_credito=PlanCredito.PLAN_10,
        tipo_credito=TipoCredito.NOMINA_TARJETA,
        docs_ine=True,
        docs_comprobante=True,
        docs_estados_de_cuenta=True,
        docs_nomina=True,
    )
    assert next_pending_doc(s, PlanCredito.PLAN_10, _DOCS_PER_PLAN) is None


def test_next_pending_doc_minimal_plan_sin_comprobantes() -> None:
    """Plan 'Sin Comprobantes' solo requiere INE + comprobante de domicilio."""
    s = ExtractedFields(
        plan_credito=PlanCredito.PLAN_20,
        tipo_credito=TipoCredito.SIN_COMPROBANTES,
    )
    assert next_pending_doc(s, PlanCredito.PLAN_20, _DOCS_PER_PLAN) == "ine"

    s.docs_ine = True
    assert next_pending_doc(s, PlanCredito.PLAN_20, _DOCS_PER_PLAN) == "comprobante"

    s.docs_comprobante = True
    assert next_pending_doc(s, PlanCredito.PLAN_20, _DOCS_PER_PLAN) is None
