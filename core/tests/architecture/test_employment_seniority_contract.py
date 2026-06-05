from datetime import date
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from atendia.api.customer_fields_routes import FieldDefCreate, _canonicalize_field_value
from atendia.runner.employment_seniority_policy import (
    ANTIGUEDAD_LABORAL_FIELD_KEY,
    ANTIGUEDAD_LABORAL_FIELD_OPTIONS,
    ANTIGUEDAD_LABORAL_FIELD_TYPE,
    employment_seniority_field_updates,
    is_ambiguous_seniority_reply,
    is_valid_seniority_duration,
    parse_employment_seniority,
)
from atendia.runner.state_write_policy import (
    STATE_GUARD_PROTECTED_FIELDS,
    StateWritePolicyRequest,
    apply_state_write_policy,
)


def test_parse_employment_seniority_years() -> None:
    result = parse_employment_seniority("2 a\u00f1os")

    assert result is not None
    assert result.raw_text == "2 a\u00f1os"
    assert result.normalized_amount == 2
    assert result.normalized_unit == "years"
    assert result.normalized_months == 24
    assert result.display_value == "2 a\u00f1os"


def test_parse_employment_seniority_months() -> None:
    result = parse_employment_seniority("6 meses")

    assert result is not None
    assert result.normalized_amount == 6
    assert result.normalized_unit == "months"
    assert result.normalized_months == 6
    assert result.display_value == "6 meses"


@pytest.mark.parametrize(
    ("text", "months"),
    [
        ("tengo 15 a\u00f1os", 180),
        ("desde hace un a\u00f1o", 12),
        ("1 ano", 12),
        ("un ano", 12),
        ("medio ano", 6),
    ],
)
def test_parse_employment_seniority_common_phrases(text: str, months: int) -> None:
    result = parse_employment_seniority(text)

    assert result is not None
    assert result.normalized_months == months


@pytest.mark.parametrize("text", ["s\u00ed", "ok", "va", "sale", "mas o menos", "poquito", "no se"])
def test_ambiguous_seniority_replies_do_not_parse_as_duration(text: str) -> None:
    assert is_ambiguous_seniority_reply(text) is True
    assert is_valid_seniority_duration(text) is False
    assert parse_employment_seniority(text) is None


def test_employment_seniority_field_update_derives_filtro_and_start_date() -> None:
    updates = employment_seniority_field_updates("2 a\u00f1os")

    assert set(updates) == {ANTIGUEDAD_LABORAL_FIELD_KEY, "FILTRO"}
    assert updates[ANTIGUEDAD_LABORAL_FIELD_KEY]["normalized_months"] == 24
    assert updates["FILTRO"] is True
    assert ANTIGUEDAD_LABORAL_FIELD_OPTIONS["derived_fields"]["FILTRO"]["enabled"] is True
    assert ANTIGUEDAD_LABORAL_FIELD_OPTIONS["derived_fields"]["FILTRO"]["threshold_months"] == 6


@pytest.mark.parametrize(
    ("text", "months", "start_date"),
    [
        ("desde octubre del año pasado", 7, "2025-10-01"),
        ("desde enero", 4, "2026-01-01"),
    ],
)
def test_parse_employment_seniority_relative_month_expressions(
    text: str,
    months: int,
    start_date: str,
) -> None:
    result = parse_employment_seniority(text, reference_date=date(2026, 5, 28))

    assert result is not None
    assert result.normalized_months == months
    assert result.estimated_start_date == start_date


def test_duration_customer_field_type_is_accepted_and_stored_as_normalized_string() -> None:
    body = FieldDefCreate(
        key=ANTIGUEDAD_LABORAL_FIELD_KEY,
        label="Antiguedad laboral",
        field_type=ANTIGUEDAD_LABORAL_FIELD_TYPE,
    )
    defn = SimpleNamespace(
        key=ANTIGUEDAD_LABORAL_FIELD_KEY,
        field_type=body.field_type,
        field_options=None,
    )

    assert body.field_type == "duration"
    assert _canonicalize_field_value(defn, "2 anos") == "2 a\u00f1os"

    with pytest.raises(HTTPException):
        _canonicalize_field_value(defn, "ok")


def test_state_write_policy_protects_seniority_but_allows_initial_write_and_correction() -> None:
    six_months = parse_employment_seniority("6 meses")
    two_years = parse_employment_seniority("2 a\u00f1os")
    assert six_months is not None
    assert two_years is not None

    assert ANTIGUEDAD_LABORAL_FIELD_KEY in STATE_GUARD_PROTECTED_FIELDS

    initial = apply_state_write_policy(
        StateWritePolicyRequest(
            current_state={},
            proposed_updates={
                ANTIGUEDAD_LABORAL_FIELD_KEY: six_months.as_structured_value(),
                "CREDITO": "Sin Comprobantes",
            },
            nlu_entities={
                ANTIGUEDAD_LABORAL_FIELD_KEY: six_months.as_structured_value(),
                "CREDITO": "Sin Comprobantes",
            },
            turn_context={"pipeline": SimpleNamespace(), "inbound_text": "6 meses"},
        )
    )
    assert initial.approved_updates[ANTIGUEDAD_LABORAL_FIELD_KEY]["normalized_months"] == 6
    assert initial.approved_updates["CREDITO"] == "Sin Comprobantes"
    assert initial.blocked_updates == []

    blocked = apply_state_write_policy(
        StateWritePolicyRequest(
            current_state={
                ANTIGUEDAD_LABORAL_FIELD_KEY: {"value": six_months.as_structured_value()}
            },
            proposed_updates={ANTIGUEDAD_LABORAL_FIELD_KEY: two_years.as_structured_value()},
            nlu_entities={ANTIGUEDAD_LABORAL_FIELD_KEY: two_years.as_structured_value()},
            turn_context={"pipeline": SimpleNamespace(), "inbound_text": "2 anos"},
        )
    )
    assert blocked.approved_updates == {}
    assert blocked.blocked_updates[0]["field"] == ANTIGUEDAD_LABORAL_FIELD_KEY

    corrected = apply_state_write_policy(
        StateWritePolicyRequest(
            current_state={
                ANTIGUEDAD_LABORAL_FIELD_KEY: {"value": six_months.as_structured_value()}
            },
            proposed_updates={ANTIGUEDAD_LABORAL_FIELD_KEY: two_years.as_structured_value()},
            nlu_entities={ANTIGUEDAD_LABORAL_FIELD_KEY: two_years.as_structured_value()},
            turn_context={"pipeline": SimpleNamespace(), "inbound_text": "correccion, 2 anos"},
        )
    )
    assert corrected.approved_updates[ANTIGUEDAD_LABORAL_FIELD_KEY]["normalized_months"] == 24
    assert corrected.blocked_updates == []
