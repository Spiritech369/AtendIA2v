"""ExtractedFields canonical conversation-scoped state contract.

Lives in conversation_state.extracted_data JSONB. NLU populates it,
the router reads it, the composer reads it. Hardcoded structure
(Phase 3c.2 has only Dinamo as tenant; refactor to JSONB-config when
a second vertical onboards).
"""

import pytest
from pydantic import ValidationError

from atendia.contracts.extracted_fields import (
    ExtractedFields,
    PlanCredito,
    TipoCredito,
)


def test_default_state_all_empty() -> None:
    """A fresh customer has nothing set."""
    state = ExtractedFields()
    assert state.tipo_credito is None
    assert state.plan_credito is None
    assert state.modelo_moto is None
    assert state.docs_ine is False
    assert state.docs_comprobante is False
    assert state.papeleria_completa is False
    assert state.antigüedad_meses is None


def test_tipo_credito_enum_values() -> None:
    """All 5 tipos del v1 prompt están en el enum."""
    assert TipoCredito.NOMINA_TARJETA == "Nómina Tarjeta"
    assert TipoCredito.NOMINA_RECIBOS == "Nómina Recibos"
    assert TipoCredito.PENSIONADOS == "Pensionados"
    assert TipoCredito.NEGOCIO_SAT == "Negocio SAT"
    assert TipoCredito.SIN_COMPROBANTES == "Sin Comprobantes"


def test_plan_credito_enum_values() -> None:
    """3 porcentajes del v1: 10%, 15%, 20%."""
    assert PlanCredito.PLAN_10 == "10%"
    assert PlanCredito.PLAN_15 == "15%"
    assert PlanCredito.PLAN_20 == "20%"


def test_invalid_tipo_credito_rejected() -> None:
    """Random strings rechazados con ValidationError."""
    with pytest.raises(ValidationError):
        ExtractedFields(tipo_credito="Pirata")  # type: ignore[arg-type]


def test_full_state_round_trip_through_json() -> None:
    """Pydantic serializa/deserializa para JSONB storage."""
    state = ExtractedFields(
        antigüedad_meses=24,
        tipo_credito=TipoCredito.NOMINA_TARJETA,
        plan_credito=PlanCredito.PLAN_10,
        modelo_moto="Adventure Elite 150 CC",
        docs_ine=True,
    )
    raw = state.model_dump(mode="json")
    assert raw["plan_credito"] == "10%"
    rebuilt = ExtractedFields.model_validate(raw)
    assert rebuilt.plan_credito == PlanCredito.PLAN_10


def test_partial_dict_validates() -> None:
    """Solo algunos campos también es válido (defaults aplican)."""
    state = ExtractedFields.model_validate({"antigüedad_meses": 12})
    assert state.antigüedad_meses == 12
    assert state.docs_ine is False
