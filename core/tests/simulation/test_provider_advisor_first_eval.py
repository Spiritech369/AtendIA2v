from atendia.simulation.provider_advisor_first_eval import (
    ProviderCaseAudit,
    _fallback_reliability_snapshot,
    _model_emitted_internal_error_notes,
    _progress_guard_block_rate,
    _progress_guard_sanitization_within_gate,
    _provider_eval_circuit_scope,
    _provider_eval_circuit_tenant_id,
    _provider_payload,
    _trusted_composer_human_review_notes,
    provider_eval_case_specs,
)
from atendia.simulation.provider_stability_eval import _summary_failure_cause


def test_progress_guard_gate_uses_rate_not_absolute_count() -> None:
    assert _progress_guard_block_rate(progress_sanitized=8, total_turns=200) == 0.04
    assert _progress_guard_sanitization_within_gate(
        progress_sanitized=8,
        total_turns=200,
    )


def test_progress_guard_gate_blocks_rates_above_canary_threshold() -> None:
    assert _progress_guard_block_rate(progress_sanitized=11, total_turns=200) == 0.055
    assert not _progress_guard_sanitization_within_gate(
        progress_sanitized=11,
        total_turns=200,
    )


def test_provider_eval_case_id_filters_single_adversarial_case() -> None:
    cases = provider_eval_case_specs({"adv_15"})

    assert len(cases) == 1
    assert cases[0][0].case_id == "adv_15"
    assert cases[0][1] == "adversarial"


def test_provider_eval_case_id_rejects_unknown_case() -> None:
    try:
        provider_eval_case_specs({"missing_case"})
    except ValueError as exc:
        assert "missing_case" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("unknown case id should fail")


def test_provider_eval_circuit_scope_is_case_isolated() -> None:
    assert _provider_eval_circuit_scope("adv_15") != _provider_eval_circuit_scope("adv_18")
    assert (
        _provider_eval_circuit_tenant_id("tenant-a", _provider_eval_circuit_scope("adv_15"))
        == "tenant-a:provider_eval:adv_15"
    )


def test_stability_failure_cause_distinguishes_provider_and_response_failures() -> None:
    assert _summary_failure_cause(
        {
            "definition_of_done_pass": False,
            "cases_passed": 36,
            "cases_total": 40,
            "provider_circuit_breaker_open_count": 1,
        }
    ) == "provider_circuit_open"
    assert _summary_failure_cause(
        {
            "definition_of_done_pass": False,
            "cases_passed": 36,
            "cases_total": 40,
            "repeated_question_rate": 0.01,
        }
    ) == "response_repetition_or_template"


def test_provider_eval_definition_of_done_requires_all_cases_pass() -> None:
    payload = _provider_payload(
        [
            ProviderCaseAudit(
                case_id="adv_15",
                title="Cambio despues de documentos",
                source="adversarial",
                pass_fail="fail",
                transcript=[],
                turns=[],
                final_pipeline_stage="nuevos",
                naturalidad_score=5.0,
                repeated_question_detected=False,
                stale_quote_detected=False,
                robotic_phrase_score=0.0,
                failures=["robotic_template"],
            )
        ],
        {"summary": {"cases_passed": 10}},
    )

    assert payload["summary"]["cases_passed"] == 0
    assert payload["summary"]["definition_of_done_pass"] is False


def test_model_emitted_provider_error_notes_are_not_trusted_as_provider_metrics() -> None:
    raw_payload = {
        "human_review_notes": [
            "composer_provider_error:ProviderCircuitOpenError",
            "needs_manual_review_for_context",
        ]
    }

    assert _trusted_composer_human_review_notes(
        raw_payload,
        model_response_succeeded=True,
    ) == ["needs_manual_review_for_context"]
    assert _model_emitted_internal_error_notes(
        raw_payload,
        model_response_succeeded=True,
    ) == ["composer_provider_error:ProviderCircuitOpenError"]
    assert _trusted_composer_human_review_notes(
        raw_payload,
        model_response_succeeded=False,
    ) == [
        "composer_provider_error:ProviderCircuitOpenError",
        "needs_manual_review_for_context",
    ]


def test_fallback_reliability_snapshot_prefers_preserved_layer_snapshot() -> None:
    exc = Exception("429 Too Many Requests")
    exc.provider_reliability_snapshot = {
        "provider_429_count": 3,
        "provider_retry_count": 2,
        "provider_retry_exhausted_count": 1,
        "provider_fallback_response_count": 1,
    }

    assert _fallback_reliability_snapshot(exc) == exc.provider_reliability_snapshot
