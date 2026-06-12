"""Canonical CRM persistence is a pure no-op unless the deployment opted in,
and value coercion never guesses."""

import pytest

from atendia.product_agents.respond_style_canonical_fields import (
    CANONICAL_FIELDS_FLAG,
    _coerce,
    persist_canonical_fields,
)


class _Deployment:
    def __init__(self, metadata):
        self.metadata_json = metadata


class _Def:
    def __init__(self, field_type, field_options=None):
        self.field_type = field_type
        self.field_options = field_options or {}


@pytest.mark.asyncio
async def test_noop_without_flag() -> None:
    result = await persist_canonical_fields(
        None,
        deployment=_Deployment({}),
        tenant_id="00000000-0000-0000-0000-000000000001",
        conversation_id="00000000-0000-0000-0000-000000000002",
        audit_entries=[],
    )
    assert result is None


@pytest.mark.asyncio
async def test_noop_with_non_true_flag() -> None:
    for value in (False, "true", 1, None):
        result = await persist_canonical_fields(
            None,
            deployment=_Deployment({CANONICAL_FIELDS_FLAG: value}),
            tenant_id="00000000-0000-0000-0000-000000000001",
            conversation_id="00000000-0000-0000-0000-000000000002",
            audit_entries=[],
        )
        assert result is None


def test_coerce_checkbox() -> None:
    definition = _Def("checkbox")
    assert _coerce(definition, "si") == "true"
    assert _coerce(definition, "Sí") == "true"
    assert _coerce(definition, "no") == "false"
    assert _coerce(definition, "tal vez") is None


def test_coerce_select_uses_choices_fold_match() -> None:
    definition = _Def(
        "select",
        {"choices": ["Nómina Tarjeta", "Nómina Recibos"]},
    )
    assert _coerce(definition, "nomina tarjeta") == "Nómina Tarjeta"
    assert _coerce(definition, "otro plan") is None


def test_coerce_checkbox_with_configured_values() -> None:
    definition = _Def(
        "checkbox",
        {"true_values": ["completo"], "false_values": ["incompleto"]},
    )
    assert _coerce(definition, "completo") == "true"
    assert _coerce(definition, "incompleto") == "false"
    assert _coerce(definition, "si") is None


def test_doc_counters() -> None:
    from atendia.product_agents.respond_style_canonical_fields import (
        _doc_target_state,
    )

    estados = {
        "aliases": ["estado_cuenta"],
        "required_for_plans": ["Nómina Tarjeta"],
        "required_count": 2,
    }
    # 1 de 2 estados -> pendiente con contador, no recibido
    assert (
        _doc_target_state(
            estados,
            plan_value="Nómina Tarjeta",
            items=["estado_cuenta_marzo"],
            lookup={},
        )
        == "pendiente (1/2)"
    )
    # 2 distintos -> recibido
    assert (
        _doc_target_state(
            estados,
            plan_value="Nómina Tarjeta",
            items=["estado_cuenta_marzo", "estado_cuenta_abril"],
            lookup={},
        )
        == "recibido"
    )
    # el mismo mes repetido NO suma
    assert (
        _doc_target_state(
            estados,
            plan_value="Nómina Tarjeta",
            items=["estado_cuenta_marzo", "estado_cuenta_marzo"],
            lookup={},
        )
        == "pendiente (1/2)"
    )


def test_doc_counter_by_periodicity() -> None:
    from atendia.product_agents.respond_style_canonical_fields import (
        _doc_target_state,
    )

    recibos = {
        "aliases": ["recibo_nomina"],
        "required_for_plans": ["Nómina Tarjeta"],
        "required_count_by": {
            "field": "payment_frequency",
            "map": {"semanal": 4, "quincenal": 2},
            "default": 4,
        },
    }
    semana = ["recibo_nomina_semana_14"]
    # semanal: 1 de 4
    assert (
        _doc_target_state(
            recibos,
            plan_value="Nómina Tarjeta",
            items=semana,
            lookup={"payment_frequency": "semanal"},
        )
        == "pendiente (1/4)"
    )
    # quincenal: 2 completan
    assert (
        _doc_target_state(
            recibos,
            plan_value="Nómina Tarjeta",
            items=["recibo_nomina_quincena_1", "recibo_nomina_quincena_2"],
            lookup={"payment_frequency": "quincenal"},
        )
        == "recibido"
    )
    # periodicidad desconocida -> default 4
    assert (
        _doc_target_state(
            recibos,
            plan_value="Nómina Tarjeta",
            items=semana,
            lookup={},
        )
        == "pendiente (1/4)"
    )
    # un estado de cuenta jamas cuenta como nomina
    assert (
        _doc_target_state(
            recibos,
            plan_value="Nómina Tarjeta",
            items=["estado_cuenta_abril"],
            lookup={"payment_frequency": "semanal"},
        )
        == "pendiente"
    )


def test_doc_counter_per_plan() -> None:
    from atendia.product_agents.respond_style_canonical_fields import (
        _doc_target_state,
    )

    recibos = {
        "aliases": ["recibo_nomina"],
        "required_for_plans": ["Nómina Recibos", "Nómina Tarjeta"],
        "required_count_by_plan": {
            "Nómina Recibos": {
                "field": "payment_frequency",
                "map": {"semanal": 8, "quincenal": 4, "mensual": 2},
                "default": 8,
            },
            "Nómina Tarjeta": {
                "field": "payment_frequency",
                "map": {"semanal": 4, "quincenal": 2, "mensual": 1},
                "default": 4,
            },
        },
    }
    una = ["recibo_nomina_semana_14"]
    # plan Recibos semanal: 1 de 8 (2 meses)
    assert (
        _doc_target_state(
            recibos,
            plan_value="Nómina Recibos",
            items=una,
            lookup={"payment_frequency": "semanal"},
        )
        == "pendiente (1/8)"
    )
    # plan Tarjeta semanal: 1 de 4 (1 mes)
    assert (
        _doc_target_state(
            recibos,
            plan_value="Nómina Tarjeta",
            items=una,
            lookup={"payment_frequency": "semanal"},
        )
        == "pendiente (1/4)"
    )
    # plan Tarjeta mensual: 1 de 1 -> recibido
    assert (
        _doc_target_state(
            recibos,
            plan_value="Nómina Tarjeta",
            items=["recibo_nomina_abril"],
            lookup={"payment_frequency": "mensual"},
        )
        == "recibido"
    )


def test_coerce_text_joins_lists() -> None:
    definition = _Def("text")
    assert _coerce(definition, ["ine", "recibo de luz"]) == "ine, recibo de luz"
    assert _coerce(definition, "  ") is None
