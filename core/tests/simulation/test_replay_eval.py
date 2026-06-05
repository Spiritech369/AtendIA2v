from __future__ import annotations

import json

import atendia.simulation.replay_eval as replay_eval
from atendia.simulation.replay_eval import audit_replay_dataset, run_replay_eval


def test_replay_eval_allows_quote_after_prior_product_context(tmp_path):
    dataset = {
        "version": 1,
        "anonymized": True,
        "raw_text_exported": False,
        "cases": [
            {
                "case_id": "sim_quote_after_product",
                "expected_tags": ["quote"],
                "turns": [
                    {"customer": "cliente menciona interes en moto modelo anonimo"},
                    {"customer": "cliente solicita cotizacion"},
                ],
            }
        ],
    }
    path = tmp_path / "dataset.json"
    path.write_text(json.dumps(dataset), encoding="utf-8")

    payload = run_replay_eval(path, anonymized=True)

    assert payload["summary"]["replay_cases_passed"] == 1
    assert payload["summary"]["critical_failure_count"] == 0
    assert payload["cases"][0]["turns_to_quote"] == 2


def test_replay_eval_allows_product_after_prior_quote_intent(tmp_path):
    dataset = {
        "version": 1,
        "anonymized": True,
        "raw_text_exported": False,
        "cases": [
            {
                "case_id": "sim_product_after_quote",
                "expected_tags": ["quote"],
                "turns": [
                    {"customer": "cliente solicita cotizacion"},
                    {"customer": "cliente menciona interes en moto modelo anonimo"},
                ],
            }
        ],
    }
    path = tmp_path / "dataset.json"
    path.write_text(json.dumps(dataset), encoding="utf-8")

    payload = run_replay_eval(path, anonymized=True)

    assert payload["summary"]["replay_cases_passed"] == 1
    assert payload["summary"]["critical_failure_count"] == 0
    assert payload["cases"][0]["turns_to_quote"] == 2


def test_replay_eval_still_blocks_quote_without_product_context(tmp_path):
    dataset = {
        "version": 1,
        "anonymized": True,
        "raw_text_exported": False,
        "cases": [
            {
                "case_id": "sim_quote_without_product",
                "expected_tags": ["quote"],
                "turns": [{"customer": "cliente solicita cotizacion"}],
            }
        ],
    }
    path = tmp_path / "dataset.json"
    path.write_text(json.dumps(dataset), encoding="utf-8")

    payload = run_replay_eval(path, anonymized=True)

    assert payload["summary"]["replay_cases_passed"] == 0
    assert payload["summary"]["critical_failure_count"] == 1
    assert payload["cases"][0]["critical_failures"] == ["expected_quote_not_replayable"]


def test_replay_eval_accepts_tenant_domain_contract(tmp_path, monkeypatch):
    dataset = {
        "version": 1,
        "anonymized": True,
        "raw_text_exported": False,
        "source": "unit_test",
        "cases": [
            {
                "case_id": "real_shadow_quote",
                "conversation_hash": "abc123",
                "expected_tags": ["quote"],
                "turns": [
                    {"customer": "cliente solicita cotizacion"},
                    {"customer": "cliente menciona interes en moto modelo anonimo"},
                ],
            }
        ],
    }
    contract = {
        "tenant_id": "tenant-test",
        "agent_id": "agent-test",
        "domain": "vehicle_credit_sales",
        "runtime_mode": "v2_shadow_until_evaluated",
        "live_send_enabled": False,
        "actions_enabled": False,
        "workflow_side_effects_enabled": False,
        "canary_enabled": False,
        "single_contact_smoke_enabled": False,
        "pipeline": {"id": "shadow_pipeline", "dry_run": True},
    }
    dataset_path = tmp_path / "dataset.json"
    contract_path = tmp_path / "contract.json"
    dataset_path.write_text(json.dumps(dataset), encoding="utf-8")
    contract_path.write_text(json.dumps(contract), encoding="utf-8")
    for name in (
        "DINAMO_REPLAY_JSON",
        "DINAMO_REPLAY_MD",
        "DATASET_AUDIT_JSON",
        "DATASET_AUDIT_MD",
        "TRANSCRIPTS_JSON",
        "TRANSCRIPTS_MD",
        "HUMAN_REVIEW_JSON",
        "HUMAN_REVIEW_MD",
        "INCOHERENCE_JSON",
        "INCOHERENCE_MD",
        "E2E_VS_REAL_JSON",
        "E2E_VS_REAL_MD",
        "READINESS_JSON",
        "READINESS_MD",
    ):
        suffix = ".md" if name.endswith("_MD") else ".json"
        monkeypatch.setattr(replay_eval, name, tmp_path / f"{name.lower()}{suffix}")

    audit = audit_replay_dataset(dataset_path, tenant_domain_contract=contract_path)
    payload = run_replay_eval(
        dataset_path,
        anonymized=True,
        tenant_domain_contract=contract_path,
    )

    assert audit["decision"] == "DATASET_AUDIT_PASS_LOW_SAMPLE"
    assert payload["tenant_domain_contract"]["domain"] == "vehicle_credit_sales"
    assert payload["summary"]["tenant_contract_safety_flags_pass"] is True
    assert payload["summary"]["critical_failure_count"] == 0
    assert payload["summary"]["side_effect_count"] == 0
    assert payload["summary"]["whatsapp_sent_count"] == 0
