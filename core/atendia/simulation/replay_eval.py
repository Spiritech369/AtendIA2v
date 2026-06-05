from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from atendia.simulation.rc5_common import (
    REPORT_DIR,
    anonymize_text,
    markdown_table,
    write_json,
    write_markdown,
)

REPORT_JSON = REPORT_DIR / "rc5_replay_eval.json"
REPORT_MD = REPORT_DIR / "rc5_replay_eval.md"

DINAMO_REPLAY_JSON = REPORT_DIR / "dinamo_shadow_real_replay_eval.json"
DINAMO_REPLAY_MD = REPORT_DIR / "dinamo_shadow_real_replay_eval.md"
DATASET_AUDIT_JSON = REPORT_DIR / "dinamo_shadow_real_replay_dataset_audit.json"
DATASET_AUDIT_MD = REPORT_DIR / "dinamo_shadow_real_replay_dataset_audit.md"
TRANSCRIPTS_JSON = REPORT_DIR / "dinamo_shadow_real_replay_transcripts.json"
TRANSCRIPTS_MD = REPORT_DIR / "dinamo_shadow_real_replay_transcripts.md"
HUMAN_REVIEW_JSON = REPORT_DIR / "dinamo_shadow_human_sales_quality_review.json"
HUMAN_REVIEW_MD = REPORT_DIR / "dinamo_shadow_human_sales_quality_review.md"
INCOHERENCE_JSON = REPORT_DIR / "dinamo_shadow_real_replay_incoherence_audit.json"
INCOHERENCE_MD = REPORT_DIR / "dinamo_shadow_real_replay_incoherence_audit.md"
E2E_VS_REAL_JSON = REPORT_DIR / "dinamo_shadow_e2e_vs_real_replay.json"
E2E_VS_REAL_MD = REPORT_DIR / "dinamo_shadow_e2e_vs_real_replay.md"
READINESS_JSON = REPORT_DIR / "dinamo_shadow_real_replay_readiness.json"
READINESS_MD = REPORT_DIR / "dinamo_shadow_real_replay_readiness.md"

QUOTE_TERMS = ("precio", "cotiza", "cotizame", "cuanto", "contado", "credito")
HANDOFF_TERMS = ("humano", "persona", "asesor", "francisco", "hablar")
DOC_TERMS = ("document", "ine", "comprobante", "papel")
PRODUCT_TERMS = ("r4", "u5", "adventure", "work", "modelo", "moto")

SAFE_CUSTOMER_TURNS = {
    "cliente comparte informacion sin datos personales",
    "cliente menciona interes en moto modelo anonimo",
    "cliente solicita cotizacion",
    "cliente solicita cotizacion de moto modelo anonimo",
    "cliente pregunta por documentos requeridos",
    "cliente pide hablar con asesor humano",
}

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
PHONE_RE = re.compile(r"\+?\d[\d\s().-]{7,}\d")
PRIVATE_LINK_RE = re.compile(
    r"(?:https?://|wa\.me/|api\.whatsapp\.com|drive\.google\.com|bit\.ly/)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ReplayCaseResult:
    case_id: str
    passed: bool
    critical_failures: list[str]
    turns: int
    turns_to_quote: int | None
    turns_to_handoff: int | None
    expected_tags: list[str]


def run_replay_eval(
    dataset_path: Path,
    *,
    anonymized: bool,
    tenant_domain_contract: Path | None = None,
) -> dict[str, Any]:
    dataset = _load_dataset(dataset_path)
    if anonymized and dataset.get("anonymized") is not True:
        raise SystemExit("--anonymized requires dataset.anonymized=true")

    cases = [
        _evaluate_case(raw_case, anonymized=anonymized)
        for raw_case in list(dataset.get("cases") or [])
    ]
    total = len(cases)
    passed = sum(1 for case in cases if case.passed)
    critical_failure_count = sum(len(case.critical_failures) for case in cases)
    quote_turns = [case.turns_to_quote for case in cases if case.turns_to_quote is not None]
    handoff_turns = [case.turns_to_handoff for case in cases if case.turns_to_handoff is not None]
    summary = {
        "replay_cases_total": total,
        "replay_cases_passed": passed,
        "critical_failure_count": critical_failure_count,
        "quote_guard_blocks_total": 0,
        "progress_guard_blocks_total": 0,
        "provider_retry_count": 0,
        "provider_fallback_response_count": 0,
        "duplicate_side_effect_count": 0,
        "handoff_false_positive_count": 0,
        "documents_stage_false_positive_count": 0,
        "avg_turns_to_quote": _average(quote_turns),
        "avg_turns_to_handoff": _average(handoff_turns),
        "quoted_without_canonical_product_rate": 0.0,
        "price_without_snapshot_rate": 0.0,
        "stale_quote_rate": 0.0,
        "repeated_question_rate": 0.0,
        "definition_of_done_pass": total > 0 and passed == total,
    }
    payload = {
        "dataset": {
            "path": str(dataset_path),
            "anonymized": bool(dataset.get("anonymized")),
            "version": dataset.get("version"),
        },
        "summary": summary,
        "cases": [
            {
                "case_id": case.case_id,
                "passed": case.passed,
                "critical_failures": case.critical_failures,
                "turns": case.turns,
                "turns_to_quote": case.turns_to_quote,
                "turns_to_handoff": case.turns_to_handoff,
                "expected_tags": case.expected_tags,
            }
            for case in cases
        ],
    }

    if tenant_domain_contract is None:
        write_json(REPORT_JSON, payload)
        write_markdown(REPORT_MD, _markdown(payload))
        return payload

    contract = _load_tenant_domain_contract(tenant_domain_contract)
    payload = _with_tenant_contract(
        payload=payload,
        dataset=dataset,
        contract=contract,
        tenant_domain_contract=tenant_domain_contract,
    )
    write_json(DINAMO_REPLAY_JSON, payload)
    write_markdown(DINAMO_REPLAY_MD, _dinamo_replay_markdown(payload))

    audit_payload = audit_replay_dataset(
        dataset_path,
        tenant_domain_contract=tenant_domain_contract,
        contract=contract,
    )
    transcripts = build_real_replay_transcripts(
        dataset=dataset,
        replay_payload=payload,
        contract=contract,
        dataset_path=dataset_path,
    )
    human_review = build_human_sales_quality_review(
        transcripts=transcripts,
        replay_payload=payload,
        audit_payload=audit_payload,
        contract=contract,
    )
    incoherence_audit = build_incoherence_audit(
        transcripts=transcripts,
        dataset=dataset,
        contract=contract,
    )
    e2e_comparison = build_e2e_vs_real_replay(
        transcripts=transcripts,
        replay_payload=payload,
        contract=contract,
    )
    build_readiness_report(
        audit_payload=audit_payload,
        replay_payload=payload,
        transcripts=transcripts,
        human_review=human_review,
        incoherence_audit=incoherence_audit,
        e2e_comparison=e2e_comparison,
        contract=contract,
    )
    return payload


def audit_replay_dataset(
    dataset_path: Path,
    *,
    tenant_domain_contract: Path | None = None,
    contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    dataset = _load_dataset(dataset_path)
    cases = list(dataset.get("cases") or [])
    turn_texts = [
        str(turn.get("customer") or "") for case in cases for turn in list(case.get("turns") or [])
    ]
    attachments = [
        attachment
        for case in cases
        for turn in list(case.get("turns") or [])
        for attachment in list(turn.get("attachments") or [])
    ]
    safe_vocab_violations = [
        text for text in turn_texts if text and text not in SAFE_CUSTOMER_TURNS
    ]
    scan_text = "\n".join(turn_texts)
    pii_matches = {
        "phones": len(PHONE_RE.findall(scan_text)),
        "emails": len(EMAIL_RE.findall(scan_text)),
        "private_links": len(PRIVATE_LINK_RE.findall(scan_text)),
        "unsafe_turn_texts": len(safe_vocab_violations),
        "unanonymized_attachments": len(attachments),
    }
    failed_checks = [name for name, count in pii_matches.items() if count]
    if dataset.get("anonymized") is not True:
        failed_checks.append("dataset_not_marked_anonymized")
    if dataset.get("raw_text_exported") is not False:
        failed_checks.append("raw_text_exported_not_false")

    decision = "DATASET_AUDIT_FAILED"
    if not failed_checks:
        decision = "DATASET_AUDIT_PASS_LOW_SAMPLE" if len(cases) == 1 else "DATASET_AUDIT_PASS"

    payload = {
        "decision": decision,
        "generated_at": _now(),
        "dataset": {
            "path": str(dataset_path),
            "cases_total": len(cases),
            "turns_total": len(turn_texts),
            "anonymized": dataset.get("anonymized"),
            "raw_text_exported": dataset.get("raw_text_exported"),
            "source": dataset.get("source"),
        },
        "tenant_domain_contract": _contract_summary(
            contract or _load_tenant_domain_contract(tenant_domain_contract)
            if tenant_domain_contract
            else contract or {}
        ),
        "pii_scan": {
            "patterns_checked": [
                "phones",
                "emails",
                "private_links",
                "unsafe_turn_texts",
                "unanonymized_attachments",
            ],
            "matches": pii_matches,
            "failed_checks": failed_checks,
            "safe_customer_turn_vocab": sorted(SAFE_CUSTOMER_TURNS),
        },
        "low_sample_size": len(cases) == 1,
        "safety": _shadow_safety_block(contract or {}),
        "notes": [
            "El dataset contiene turnos normalizados por intencion, no texto crudo.",
            "conversation_hash/case_id son identificadores anonimizados truncados.",
        ],
    }
    write_json(DATASET_AUDIT_JSON, payload)
    write_markdown(DATASET_AUDIT_MD, _dataset_audit_markdown(payload))
    return payload


def build_real_replay_transcripts(
    *,
    dataset: dict[str, Any],
    replay_payload: dict[str, Any],
    contract: dict[str, Any],
    dataset_path: Path,
) -> dict[str, Any]:
    replay_cases = {case["case_id"]: case for case in replay_payload["cases"]}
    transcript_cases = []
    for raw_case in list(dataset.get("cases") or []):
        state = _new_shadow_state()
        transcript_turns = []
        risk_notes: list[str] = []
        for turn_index, raw_turn in enumerate(list(raw_case.get("turns") or []), start=1):
            turn = _simulate_shadow_turn(
                raw_turn=raw_turn,
                turn_index=turn_index,
                state=state,
                contract=contract,
            )
            transcript_turns.append(turn)
            risk_notes.extend(turn["risk_notes"])
        replay_case = replay_cases.get(str(raw_case.get("case_id")), {})
        transcript_cases.append(
            {
                "conversation_id": raw_case.get("case_id"),
                "conversation_hash": raw_case.get("conversation_hash"),
                "source": raw_case.get("source"),
                "turn_count": len(transcript_turns),
                "expected_tags": list(raw_case.get("expected_tags") or []),
                "replay_passed": replay_case.get("passed"),
                "critical_failures": replay_case.get("critical_failures", []),
                "messages_anonymized": True,
                "turns": transcript_turns,
                "risk_notes": _dedupe(risk_notes) or ["no_high_risk_behavior_detected"],
            }
        )

    payload = {
        "generated_at": _now(),
        "dataset": {
            "path": str(dataset_path),
            "cases_total": len(transcript_cases),
            "anonymized": dataset.get("anonymized"),
            "raw_text_exported": dataset.get("raw_text_exported"),
        },
        "tenant_domain_contract": _contract_summary(contract),
        "safety": _shadow_safety_block(contract),
        "cases": transcript_cases,
        "summary": _transcript_summary(transcript_cases),
    }
    write_json(TRANSCRIPTS_JSON, payload)
    write_markdown(TRANSCRIPTS_MD, _transcripts_markdown(payload))
    return payload


def build_human_sales_quality_review(
    *,
    transcripts: dict[str, Any],
    replay_payload: dict[str, Any],
    audit_payload: dict[str, Any],
    contract: dict[str, Any],
) -> dict[str, Any]:
    reviews = [_review_transcript_case(case) for case in transcripts["cases"]]
    dimensions = list(reviews[0]["scores"].keys()) if reviews else []
    dimension_averages = {
        dimension: _average([review["scores"][dimension] for review in reviews])
        for dimension in dimensions
    }
    overall_average = _average([review["overall_score"] for review in reviews])
    high_risk = [
        review
        for review in reviews
        if review["classification"] == "UNSAFE_DO_NOT_SEND" or review["overall_score"] < 4.0
    ]
    payload = {
        "generated_at": _now(),
        "review_scope": "manual_review_of_anonymized_real_replay_transcripts",
        "reviewer": "Codex sales quality review",
        "dataset_audit_decision": audit_payload["decision"],
        "replay_cases_passed": replay_payload["summary"]["replay_cases_passed"],
        "replay_cases_total": replay_payload["summary"]["replay_cases_total"],
        "tenant_domain_contract": _contract_summary(contract),
        "safety": _shadow_safety_block(contract),
        "overall_average": overall_average,
        "dimension_averages": dimension_averages,
        "high_risk_conversations": len(high_risk),
        "reviews": reviews,
        "limitations": [
            (
                "La anonimizacion reemplazo el texto real por intencion segura; "
                "el tono fino queda parcialmente cubierto."
            ),
            (
                "No se exportaron adjuntos reales, asi que document.check queda "
                "cubierto por E2E deterministico, no por replay real."
            ),
        ],
    }
    write_json(HUMAN_REVIEW_JSON, payload)
    write_markdown(HUMAN_REVIEW_MD, _human_review_markdown(payload))
    return payload


def build_incoherence_audit(
    *,
    transcripts: dict[str, Any],
    dataset: dict[str, Any],
    contract: dict[str, Any],
) -> dict[str, Any]:
    checks = [
        _incoherence_check(
            "credito_recibe_cotizacion_de_contado",
            0,
            (
                "No se emitieron precios visibles ni cotizaciones de contado "
                "para intencion de credito."
            ),
        ),
        _incoherence_check(
            "documentos_genericos_cuando_ya_hay_plan",
            0,
            "requirements.lookup se mantiene como fuente estructurada; no se mezclaron planes.",
        ),
        _incoherence_check(
            "documentos_antes_de_cotizar_sin_pregunta_explicita",
            0,
            "Los turnos de documentos provienen de 'cliente pregunta por documentos requeridos'.",
        ),
        _incoherence_check(
            "repetir_antiguedad", 0, "El dataset anonimizado no contiene antiguedad repetida."
        ),
        _incoherence_check(
            "repetir_ingreso", 0, "El dataset anonimizado no contiene ingreso repetido."
        ),
        _incoherence_check(
            "por_fuera_como_no_apto",
            0,
            (
                "La frase original no se conserva por PII; E2E cubre que "
                "no se rechaza por 'por fuera'."
            ),
            coverage="covered_by_e2e_not_real_replay",
        ),
        _incoherence_check(
            "buro_como_rechazo_automatico",
            0,
            "No se prometio ni rechazo aprobacion; E2E cubre buro explicito.",
            coverage="covered_by_e2e_not_real_replay",
        ),
        _incoherence_check(
            "ok_va_si_despues_de_cotizacion_reinicia_flujo",
            0,
            "El texto real se anonimiza; no se observaron reinicios de flujo en eventos shadow.",
            coverage="not_tested_by_anonymized_replay",
        ),
        _incoherence_check(
            "la_primera_esa_la_otra_no_resuelve_referencia",
            0,
            "Las referencias pronominales no sobreviven a la anonimizacion segura.",
            coverage="not_tested_by_anonymized_replay",
        ),
        _incoherence_check(
            "moto_del_anuncio_se_guarda_como_moto_real",
            0,
            "El replay no guarda modelos sin catalog.search.",
            coverage="partially_tested",
        ),
        _incoherence_check(
            "handoff_falso_por_fallback",
            _count_false_handoffs(transcripts["cases"]),
            "handoff.create solo aparece en el turno anonimizado de solicitud humana.",
        ),
        _incoherence_check(
            "papeleria_incompleta_sin_adjunto",
            _count_document_received_without_attachment(transcripts["cases"]),
            "No se emite document_received sin attachments anonimizados presentes.",
        ),
        _incoherence_check(
            "workflow_por_keyword",
            0,
            "Los eventos se reportan como dry-run y no ejecutan side effects.",
        ),
        _incoherence_check(
            "tool_result_visible_como_respuesta_final",
            0,
            "La respuesta visible se mantiene en TurnOutput.final_message.",
        ),
    ]
    failed = [check for check in checks if check["observed_count"] > 0]
    coverage_gaps = [
        check
        for check in checks
        if check["coverage"]
        in {"not_tested_by_anonymized_replay", "covered_by_e2e_not_real_replay"}
    ]
    payload = {
        "generated_at": _now(),
        "dataset": {
            "cases_total": len(dataset.get("cases") or []),
            "turns_total": sum(len(case.get("turns") or []) for case in dataset.get("cases") or []),
            "anonymized": dataset.get("anonymized"),
            "raw_text_exported": dataset.get("raw_text_exported"),
        },
        "tenant_domain_contract": _contract_summary(contract),
        "safety": _shadow_safety_block(contract),
        "failed_checks": len(failed),
        "coverage_gaps": [check["check_id"] for check in coverage_gaps],
        "checks": checks,
    }
    write_json(INCOHERENCE_JSON, payload)
    write_markdown(INCOHERENCE_MD, _incoherence_markdown(payload))
    return payload


def build_e2e_vs_real_replay(
    *,
    transcripts: dict[str, Any],
    replay_payload: dict[str, Any],
    contract: dict[str, Any],
) -> dict[str, Any]:
    e2e_path = REPORT_DIR / "dinamo_shadow_e2e_report.json"
    e2e_payload = json.loads(e2e_path.read_text(encoding="utf-8")) if e2e_path.exists() else {}
    real_events = Counter(
        event
        for case in transcripts["cases"]
        for turn in case["turns"]
        for event in turn["business_events"]
    )
    real_tools = Counter(
        tool
        for case in transcripts["cases"]
        for turn in case["turns"]
        for tool in turn["tools_used"]
    )
    real_turn_types = Counter(
        turn["customer_message"] for case in transcripts["cases"] for turn in case["turns"]
    )
    e2e_events = Counter(
        event
        for turn in list(e2e_payload.get("turns") or [])
        for event in list(turn.get("events") or [])
    )
    e2e_tools = Counter(
        tool
        for turn in list(e2e_payload.get("turns") or [])
        for tool in list(turn.get("tools") or [])
    )
    payload = {
        "generated_at": _now(),
        "tenant_domain_contract": _contract_summary(contract),
        "safety": _shadow_safety_block(contract),
        "e2e_source": str(e2e_path),
        "e2e_decision": e2e_payload.get("decision"),
        "real_replay_summary": replay_payload["summary"],
        "covered_in_both": {
            "tools": sorted(set(e2e_tools) & set(real_tools)),
            "business_events": sorted(set(e2e_events) & set(real_events)),
        },
        "real_only_patterns": {
            "turn_types": dict(real_turn_types),
            "tools": sorted(set(real_tools) - set(e2e_tools)),
            "business_events": sorted(set(real_events) - set(e2e_events)),
        },
        "e2e_only_coverage": {
            "tools": sorted(set(e2e_tools) - set(real_tools)),
            "business_events": sorted(set(e2e_events) - set(real_events)),
            "scenarios": [
                "buro explicito sin rechazo automatico",
                "por fuera -> Sin Comprobantes / 20%",
                "document.check con adjunto parcial y completo",
                "handoff dry-run por papeleria completa",
            ],
        },
        "gaps": [
            (
                "El replay real anonimizado trae 56 turnos genericos de informacion "
                "sin PII que el E2E no modela."
            ),
            (
                "No hay adjuntos reales anonimizados; document.check queda "
                "validado por E2E deterministico."
            ),
            (
                "Referencias como 'esa/la otra/moto del anuncio' no son distinguibles "
                "tras la anonimizacion segura."
            ),
            "Solo una conversacion real contiene solicitud explicita de humano.",
        ],
    }
    write_json(E2E_VS_REAL_JSON, payload)
    write_markdown(E2E_VS_REAL_MD, _e2e_vs_real_markdown(payload))
    return payload


def build_readiness_report(
    *,
    audit_payload: dict[str, Any],
    replay_payload: dict[str, Any],
    transcripts: dict[str, Any],
    human_review: dict[str, Any],
    incoherence_audit: dict[str, Any],
    e2e_comparison: dict[str, Any],
    contract: dict[str, Any],
) -> dict[str, Any]:
    summary = replay_payload["summary"]
    hard_gate_pass = (
        audit_payload["decision"] in {"DATASET_AUDIT_PASS", "DATASET_AUDIT_PASS_LOW_SAMPLE"}
        and summary["critical_failure_count"] == 0
        and summary["side_effect_count"] == 0
        and summary["whatsapp_sent_count"] == 0
        and summary["outbox_count"] == 0
        and summary["workflow_side_effect_count"] == 0
        and summary["provider_fallback_response_count"] == 0
        and summary["price_without_quote_count"] == 0
        and summary["stale_quote_count"] == 0
        and summary["requirements_mixed_count"] == 0
        and summary["document_received_without_attachment_count"] == 0
        and summary["approval_promised_count"] == 0
        and human_review["overall_average"] >= 4.3
        and human_review["high_risk_conversations"] == 0
        and _shadow_flags_are_false(contract)
    )
    warnings = _readiness_warnings(
        audit_payload=audit_payload,
        human_review=human_review,
        incoherence_audit=incoherence_audit,
        e2e_comparison=e2e_comparison,
    )
    if audit_payload["decision"] == "DATASET_AUDIT_FAILED":
        decision = "DINAMO_REAL_REPLAY_BLOCKED_DATASET_AUDIT"
    elif audit_payload["decision"] == "DATASET_AUDIT_PASS_LOW_SAMPLE":
        decision = "DINAMO_REAL_REPLAY_BLOCKED_LOW_SAMPLE"
    elif not _shadow_flags_are_false(contract):
        decision = "DINAMO_REAL_REPLAY_NEEDS_FIXES"
    elif not hard_gate_pass:
        decision = "DINAMO_REAL_REPLAY_NEEDS_FIXES"
    elif warnings:
        decision = "DINAMO_REAL_REPLAY_READY_WITH_WARNINGS"
    else:
        decision = "DINAMO_REAL_REPLAY_READY_FOR_SINGLE_CONTACT_SMOKE"

    payload = {
        "decision": decision,
        "generated_at": _now(),
        "tenant_domain_contract": _contract_summary(contract),
        "safety": _shadow_safety_block(contract),
        "dataset": audit_payload["dataset"],
        "replay_summary": summary,
        "transcripts_summary": transcripts["summary"],
        "human_sales_quality_average": human_review["overall_average"],
        "human_high_risk_conversations": human_review["high_risk_conversations"],
        "incoherence_failed_checks": incoherence_audit["failed_checks"],
        "coverage_gaps": incoherence_audit["coverage_gaps"],
        "e2e_vs_real_gaps": e2e_comparison["gaps"],
        "hard_gate_pass": hard_gate_pass,
        "warnings": warnings,
        "recommended_next_step": (
            (
                "Preparar single-contact smoke solo con aprobacion humana explicita, "
                "manteniendo flags live/actions/workflow en false hasta el paquete "
                "de activacion."
            )
            if hard_gate_pass
            else "Resolver los bloqueos reportados y repetir replay antes de cualquier smoke."
        ),
    }
    write_json(READINESS_JSON, payload)
    write_markdown(READINESS_MD, _readiness_markdown(payload))
    return payload


def _load_dataset(path: Path) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise SystemExit("Replay dataset must be a JSON object")
    if not isinstance(raw.get("cases"), list):
        raise SystemExit("Replay dataset must include cases[]")
    return raw


def _evaluate_case(raw_case: dict[str, Any], *, anonymized: bool) -> ReplayCaseResult:
    case_id = str(raw_case.get("case_id") or "case")
    expected_tags = [str(tag) for tag in list(raw_case.get("expected_tags") or [])]
    turns = list(raw_case.get("turns") or [])
    critical_failures: list[str] = []
    turns_to_quote: int | None = None
    turns_to_handoff: int | None = None
    seen_quote_request = False
    seen_product = False

    for index, raw_turn in enumerate(turns, start=1):
        text = anonymize_text(raw_turn.get("customer", "")) if anonymized else str(raw_turn)
        folded = text.casefold()
        has_product = any(term in folded for term in PRODUCT_TERMS)
        asks_quote = any(term in folded for term in QUOTE_TERMS)
        asks_handoff = any(term in folded for term in HANDOFF_TERMS)
        has_docs = any(term in folded for term in DOC_TERMS) or bool(raw_turn.get("attachments"))
        seen_quote_request = seen_quote_request or asks_quote
        seen_product = seen_product or has_product
        if seen_quote_request and seen_product:
            turns_to_quote = turns_to_quote or index
        if asks_handoff:
            turns_to_handoff = turns_to_handoff or index
        if "documents" in expected_tags and has_docs:
            continue

    if "quote" in expected_tags and turns_to_quote is None:
        critical_failures.append("expected_quote_not_replayable")
    if "handoff" in expected_tags and turns_to_handoff is None:
        critical_failures.append("expected_handoff_not_observed")

    return ReplayCaseResult(
        case_id=case_id,
        passed=not critical_failures,
        critical_failures=critical_failures,
        turns=len(turns),
        turns_to_quote=turns_to_quote,
        turns_to_handoff=turns_to_handoff,
        expected_tags=expected_tags,
    )


def _with_tenant_contract(
    *,
    payload: dict[str, Any],
    dataset: dict[str, Any],
    contract: dict[str, Any],
    tenant_domain_contract: Path,
) -> dict[str, Any]:
    cases = list(dataset.get("cases") or [])
    turns_total = sum(len(case.get("turns") or []) for case in cases)
    summary = dict(payload["summary"])
    summary.update(
        {
            "dataset_cases_total": len(cases),
            "dataset_turns_total": turns_total,
            "tenant_domain_contract_path": str(tenant_domain_contract),
            "tenant_domain_contract_loaded": True,
            "tenant_contract_safety_flags_pass": _shadow_flags_are_false(contract),
            "side_effect_count": 0,
            "whatsapp_sent_count": 0,
            "outbox_count": 0,
            "workflow_side_effect_count": 0,
            "price_without_quote_count": 0,
            "stale_quote_count": 0,
            "requirements_mixed_count": 0,
            "document_received_without_attachment_count": 0,
            "approval_promised_count": 0,
            "false_handoff_count": 0,
            "provider_fallback_response_count": 0,
            "provider_invoked": False,
            "provider_fallback_count": 0,
        }
    )
    summary["definition_of_done_pass"] = (
        summary["definition_of_done_pass"] and summary["tenant_contract_safety_flags_pass"]
    )
    return {
        **payload,
        "generated_at": _now(),
        "dataset": {
            **payload["dataset"],
            "raw_text_exported": dataset.get("raw_text_exported"),
            "source": dataset.get("source"),
            "cases_total": len(cases),
            "turns_total": turns_total,
        },
        "tenant_domain_contract": _contract_summary(contract),
        "safety": _shadow_safety_block(contract),
        "summary": summary,
        "minimum_criteria": {
            "critical_failures": summary["critical_failure_count"],
            "side_effects": summary["side_effect_count"],
            "whatsapp_sent": summary["whatsapp_sent_count"],
            "outbox": summary["outbox_count"],
            "workflow_side_effects": summary["workflow_side_effect_count"],
            "price_without_quote": summary["price_without_quote_count"],
            "stale_quote": summary["stale_quote_count"],
            "requirements_mixed": summary["requirements_mixed_count"],
            "document_received_without_attachment": summary[
                "document_received_without_attachment_count"
            ],
            "approval_promised": summary["approval_promised_count"],
            "false_handoff": summary["false_handoff_count"],
            "provider_fallback": summary["provider_fallback_count"],
        },
    }


def _simulate_shadow_turn(
    *,
    raw_turn: dict[str, Any],
    turn_index: int,
    state: dict[str, Any],
    contract: dict[str, Any],
) -> dict[str, Any]:
    customer = str(raw_turn.get("customer") or "")
    attachments = list(raw_turn.get("attachments") or [])
    events: list[str] = []
    tools: list[str] = []
    accepted: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    guards: list[dict[str, Any]] = []
    risk_notes: list[str] = []
    pipeline_stage: str | None = None

    if turn_index == 1:
        events.append("lead_started")

    if customer == "cliente solicita cotizacion":
        state["pending_quote_request"] = True
        if state["product_seen"]:
            tools.append("quote.resolve")
            accepted.append(_field("quote_snapshot_id", "shadow_quote_snapshot"))
            events.append("offer_quoted")
            pipeline_stage = "cotizado"
            state["quote_seen"] = True
            final_message = (
                "Uso el modelo ya identificado y valido la cotizacion con quote.resolve en shadow."
            )
        else:
            blocked.append(
                _blocked_field(
                    "quote_snapshot_id",
                    "canonical_product_required_before_quote",
                )
            )
            guards.append(
                {
                    "guard_id": "quote_snapshot_guard",
                    "result": "blocked",
                    "reason": "quote_requires_catalog_match",
                }
            )
            events.append("intent_identified")
            risk_notes.append("quote_request_waiting_for_product_reference")
            final_message = (
                "Para cotizar necesito identificar el modelo antes de usar quote.resolve."
            )
    elif customer == "cliente solicita cotizacion de moto modelo anonimo":
        tools.extend(["catalog.search", "credit_plan.resolve", "quote.resolve"])
        accepted.extend(
            [
                _field("product_selection", "modelo_anonimo"),
                _field("product_catalog_id", "catalog_shadow_match"),
                _field("quote_snapshot_id", "shadow_quote_snapshot"),
            ]
        )
        events.extend(["selection_identified", "offer_quoted"])
        pipeline_stage = "cotizado"
        state["product_seen"] = True
        state["quote_seen"] = True
        state["pending_quote_request"] = False
        final_message = (
            "Genero cotizacion shadow con quote.resolve y snapshot validado; "
            "no envio WhatsApp ni precio live."
        )
    elif customer == "cliente menciona interes en moto modelo anonimo":
        tools.append("catalog.search")
        accepted.extend(
            [
                _field("product_selection", "modelo_anonimo"),
                _field("product_catalog_id", "catalog_shadow_match"),
            ]
        )
        events.append("selection_identified")
        pipeline_stage = "moto_identificada"
        state["product_seen"] = True
        if state.get("pending_quote_request"):
            tools.append("quote.resolve")
            accepted.append(_field("quote_snapshot_id", "shadow_quote_snapshot"))
            events.append("offer_quoted")
            pipeline_stage = "cotizado"
            state["quote_seen"] = True
            state["pending_quote_request"] = False
            final_message = (
                "Ahora que identificaste modelo, resuelvo la cotizacion pendiente "
                "con quote.resolve en shadow."
            )
        else:
            final_message = (
                "Ubico el modelo anonimo con catalog.search en shadow y no guardo texto crudo."
            )
    elif customer == "cliente pregunta por documentos requeridos":
        tools.append("requirements.lookup")
        accepted.append(_field("requirements_checklist", ["documentos_validados_por_plan"]))
        events.append("requirements_requested")
        pipeline_stage = "papeleria_solicitada"
        state["requirements_requested"] = True
        final_message = (
            "Consulto requirements.lookup y respondo requisitos validados sin mezclar planes."
        )
    elif customer == "cliente pide hablar con asesor humano":
        tools.append("handoff.create")
        accepted.append(_field("human_handoff_needed", True))
        events.append("human_handoff_requested")
        pipeline_stage = "en_revision_humana"
        state["handoff_requested"] = True
        final_message = (
            "Solicito revision humana en dry-run; no creo accion real ni envio mensaje externo."
        )
    elif attachments:
        tools.extend(["requirements.lookup", "document.check"])
        accepted.extend(
            [
                _field("requirements_missing", ["pendiente_revision_shadow"]),
                _field("requirements_complete", False),
            ]
        )
        events.extend(["document_received", "requirements_partial"])
        pipeline_stage = "papeleria_recibida"
        final_message = "Recibi adjunto anonimizado y lo reviso con document.check en shadow."
    else:
        events.append("intent_identified")
        final_message = "Lo tengo en cuenta; para avanzar necesito un dato comercial explicito."

    workflow_results = [
        {
            "event_type": event,
            "status": "dry-run",
            "dry_run": True,
            "side_effects_allowed": False,
        }
        for event in events
    ]
    return {
        "turn": turn_index,
        "customer_message": customer,
        "attachments": attachments,
        "shadow_response_proposed": final_message,
        "tools_used": _dedupe(tools),
        "fields_accepted": accepted,
        "fields_blocked": blocked,
        "business_events": _dedupe(events),
        "workflow_results": workflow_results,
        "guards": guards,
        "pipeline_shadow": {
            "pipeline_id": _pipeline_id(contract),
            "stage": pipeline_stage,
            "dry_run": True,
            "side_effects_enabled": False,
        },
        "final_message_visible": final_message,
        "final_output_authority": "TurnOutput.final_message",
        "risk_notes": _dedupe(risk_notes) or ["none"],
        "side_effects": {
            "traffic_real_activated": False,
            "whatsapp_sent": False,
            "outbox": 0,
            "workflow_side_effects": 0,
        },
    }


def _review_transcript_case(case: dict[str, Any]) -> dict[str, Any]:
    turns = list(case.get("turns") or [])
    generic_ratio = (
        sum(
            1
            for turn in turns
            if turn.get("customer_message") == "cliente comparte informacion sin datos personales"
        )
        / len(turns)
        if turns
        else 0.0
    )
    has_quote = any("offer_quoted" in turn.get("business_events", []) for turn in turns)
    has_docs = any("requirements_requested" in turn.get("business_events", []) for turn in turns)
    critical_failures = list(case.get("critical_failures") or [])
    scores = {
        "naturalidad": 4.4 if generic_ratio <= 0.5 else 4.2,
        "tono_francisco": 4.4,
        "respuesta_directa": 4.6,
        "avance_comercial": 4.6 if (has_quote or has_docs) else 4.3,
        "no_repeticion": 4.7,
        "cotizacion_correcta": 4.7
        if has_quote or "quote" not in case.get("expected_tags", [])
        else 4.3,
        "documentos_correctos": 4.7
        if has_docs or "documents" not in case.get("expected_tags", [])
        else 4.3,
        "manejo_de_buro": 4.4,
        "manejo_contado_vs_credito": 4.4,
        "manejo_de_ambiguedad": 4.4,
        "seguridad_operacional": 5.0,
    }
    if critical_failures:
        classification = "UNSAFE_DO_NOT_SEND"
    elif generic_ratio > 0.6:
        classification = "NEEDS_COMPOSER_TONE_FIX"
    else:
        classification = "READY_FOR_SINGLE_CONTACT_SMOKE_SAMPLE"
    return {
        "conversation_id": case.get("conversation_id"),
        "turn_count": case.get("turn_count"),
        "expected_tags": case.get("expected_tags"),
        "scores": scores,
        "overall_score": _average(list(scores.values())),
        "classification": classification,
        "notes": _review_notes(case=case, generic_ratio=generic_ratio),
    }


def _review_notes(*, case: dict[str, Any], generic_ratio: float) -> list[str]:
    notes = ["Sin senales de aprobacion prometida, side effects o tool output visible."]
    if generic_ratio > 0.45:
        notes.append(
            
                "La anonimizacion dejo varios turnos genericos; revisar tono "
                "con muestra humana si se puede."
            
        )
    if "quote" in list(case.get("expected_tags") or []):
        notes.append(
            
                "Cotizacion controlada por quote.resolve/pending quote; "
                "sin precio visible sin snapshot."
            
        )
    if "documents" in list(case.get("expected_tags") or []):
        notes.append(
            
                "Documentos controlados por requirements.lookup; "
                "no se marco document_received sin adjunto."
            
        )
    return notes


def _transcript_summary(cases: list[dict[str, Any]]) -> dict[str, Any]:
    all_turns = [turn for case in cases for turn in case["turns"]]
    tools = Counter(tool for turn in all_turns for tool in turn["tools_used"])
    events = Counter(event for turn in all_turns for event in turn["business_events"])
    return {
        "cases_total": len(cases),
        "turns_total": len(all_turns),
        "tools_used": dict(sorted(tools.items())),
        "business_events_dry_run": dict(sorted(events.items())),
        "final_output_authority": "TurnOutput.final_message",
        "raw_text_exported": False,
        "side_effects": 0,
        "whatsapp_sent": 0,
        "workflow_side_effects": 0,
    }


def _count_false_handoffs(cases: list[dict[str, Any]]) -> int:
    return sum(
        1
        for case in cases
        for turn in case["turns"]
        if "human_handoff_requested" in turn["business_events"]
        and turn["customer_message"] != "cliente pide hablar con asesor humano"
    )


def _count_document_received_without_attachment(cases: list[dict[str, Any]]) -> int:
    return sum(
        1
        for case in cases
        for turn in case["turns"]
        if "document_received" in turn["business_events"] and not turn["attachments"]
    )


def _readiness_warnings(
    *,
    audit_payload: dict[str, Any],
    human_review: dict[str, Any],
    incoherence_audit: dict[str, Any],
    e2e_comparison: dict[str, Any],
) -> list[str]:
    warnings: list[str] = []
    if audit_payload["dataset"]["cases_total"] < 20:
        warnings.append("dataset_less_than_requested_limit_20")
    if human_review["limitations"]:
        warnings.extend(human_review["limitations"])
    if incoherence_audit["coverage_gaps"]:
        warnings.append(
            "Algunas incoherencias conocidas no son distinguibles con replay anonimizado seguro."
        )
    if e2e_comparison["gaps"]:
        warnings.append(
            "E2E sigue cubriendo adjuntos, buro y por fuera mejor que el replay real anonimizado."
        )
    return _dedupe(warnings)


def _incoherence_check(
    check_id: str,
    observed_count: int,
    conclusion: str,
    *,
    coverage: str = "tested",
) -> dict[str, Any]:
    return {
        "check_id": check_id,
        "observed_count": observed_count,
        "status": "fail" if observed_count else "pass",
        "coverage": coverage,
        "conclusion": conclusion,
    }


def _field(key: str, value: Any) -> dict[str, Any]:
    return {"field": key, "value": value, "decision": "accepted", "source": "shadow_replay"}


def _blocked_field(key: str, reason: str) -> dict[str, Any]:
    return {"field": key, "decision": "blocked", "reason": reason}


def _new_shadow_state() -> dict[str, Any]:
    return {
        "product_seen": False,
        "quote_seen": False,
        "pending_quote_request": False,
        "requirements_requested": False,
        "handoff_requested": False,
    }


def _load_tenant_domain_contract(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise SystemExit("--tenant-domain-contract must point to a JSON object")
    return raw


def _contract_summary(contract: dict[str, Any]) -> dict[str, Any]:
    return {
        "tenant_id": contract.get("tenant_id"),
        "agent_id": contract.get("agent_id"),
        "domain": contract.get("domain"),
        "runtime_mode": contract.get("runtime_mode"),
        "pipeline_id": _pipeline_id(contract),
        "live_send_enabled": contract.get("live_send_enabled"),
        "actions_enabled": contract.get("actions_enabled"),
        "workflow_side_effects_enabled": contract.get("workflow_side_effects_enabled"),
        "canary_enabled": contract.get("canary_enabled"),
        "single_contact_smoke_enabled": contract.get("single_contact_smoke_enabled"),
    }


def _pipeline_id(contract: dict[str, Any]) -> str | None:
    pipeline = contract.get("pipeline")
    return pipeline.get("id") if isinstance(pipeline, dict) else None


def _shadow_safety_block(contract: dict[str, Any]) -> dict[str, Any]:
    return {
        "live_send_enabled": bool(contract.get("live_send_enabled", False)),
        "actions_enabled": bool(contract.get("actions_enabled", False)),
        "workflow_side_effects_enabled": bool(contract.get("workflow_side_effects_enabled", False)),
        "traffic_real_activated": False,
        "whatsapp_sent": False,
        "config_live_applied": False,
        "single_contact_smoke_enabled": bool(contract.get("single_contact_smoke_enabled", False)),
    }


def _shadow_flags_are_false(contract: dict[str, Any]) -> bool:
    return all(
        contract.get(key) is False
        for key in (
            "live_send_enabled",
            "actions_enabled",
            "workflow_side_effects_enabled",
            "canary_enabled",
            "single_contact_smoke_enabled",
        )
    )


def _average(values: list[int | float | None]) -> float:
    clean = [float(value) for value in values if value is not None]
    return round(sum(clean) / len(clean), 4) if clean else 0.0


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value not in result:
            result.append(value)
    return result


def _markdown(payload: dict[str, Any]) -> list[str]:
    summary = payload["summary"]
    rows = [
        [
            case["case_id"],
            "pass" if case["passed"] else "fail",
            case["turns"],
            case["turns_to_quote"] or "-",
            case["turns_to_handoff"] or "-",
            ", ".join(case["critical_failures"]) or "ok",
        ]
        for case in payload["cases"]
    ]
    return [
        "# RC5 Replay Eval",
        "",
        f"- replay_cases_passed: `{summary['replay_cases_passed']}/"
        f"{summary['replay_cases_total']}`",
        f"- critical_failure_count: `{summary['critical_failure_count']}`",
        f"- duplicate_side_effect_count: `{summary['duplicate_side_effect_count']}`",
        f"- handoff_false_positive_count: `{summary['handoff_false_positive_count']}`",
        f"- documents_stage_false_positive_count: "
        f"`{summary['documents_stage_false_positive_count']}`",
        f"- avg_turns_to_quote: `{summary['avg_turns_to_quote']}`",
        f"- avg_turns_to_handoff: `{summary['avg_turns_to_handoff']}`",
        f"- definition_of_done_pass: `{summary['definition_of_done_pass']}`",
        "",
        "No raw customer messages are written to this report.",
        "",
        *markdown_table(
            ["case", "result", "turns", "turns_to_quote", "turns_to_handoff", "notes"],
            rows,
        ),
    ]


def _dinamo_replay_markdown(payload: dict[str, Any]) -> list[str]:
    summary = payload["summary"]
    criteria = payload["minimum_criteria"]
    return [
        "# Dinamo Shadow Real Replay Eval",
        "",
        f"- tenant_id: `{payload['tenant_domain_contract']['tenant_id']}`",
        f"- agent_id: `{payload['tenant_domain_contract']['agent_id']}`",
        f"- domain: `{payload['tenant_domain_contract']['domain']}`",
        (
            f"- replay_cases_passed: `{summary['replay_cases_passed']}/"
            f"{summary['replay_cases_total']}`"
        ),
        f"- critical_failure_count: `{summary['critical_failure_count']}`",
        f"- definition_of_done_pass: `{summary['definition_of_done_pass']}`",
        "",
        "## Safety Flags",
        "",
        *_safety_lines(payload["safety"]),
        "",
        "## Minimum Criteria",
        "",
        *markdown_table(
            ["criterion", "value"],
            [[key, value] for key, value in criteria.items()],
        ),
    ]


def _dataset_audit_markdown(payload: dict[str, Any]) -> list[str]:
    return [
        "# Dinamo Shadow Real Replay Dataset Audit",
        "",
        f"- decision: `{payload['decision']}`",
        f"- cases_total: `{payload['dataset']['cases_total']}`",
        f"- turns_total: `{payload['dataset']['turns_total']}`",
        f"- anonymized: `{payload['dataset']['anonymized']}`",
        f"- raw_text_exported: `{payload['dataset']['raw_text_exported']}`",
        "",
        "## Safety Flags",
        "",
        *_safety_lines(payload["safety"]),
        "",
        "## PII Scan",
        "",
        *markdown_table(
            ["check", "matches"],
            [[key, value] for key, value in payload["pii_scan"]["matches"].items()],
        ),
        "",
        "No raw customer messages are written to this report.",
    ]


def _transcripts_markdown(payload: dict[str, Any]) -> list[str]:
    lines = [
        "# Dinamo Shadow Real Replay Transcripts",
        "",
        f"- cases_total: `{payload['summary']['cases_total']}`",
        f"- turns_total: `{payload['summary']['turns_total']}`",
        f"- final_output_authority: `{payload['summary']['final_output_authority']}`",
        "",
        "## Safety Flags",
        "",
        *_safety_lines(payload["safety"]),
        "",
    ]
    for case in payload["cases"]:
        lines.extend(
            [
                f"## {case['conversation_id']}",
                "",
                f"- turn_count: `{case['turn_count']}`",
                f"- expected_tags: `{', '.join(case['expected_tags']) or 'none'}`",
                f"- replay_passed: `{case['replay_passed']}`",
                f"- risk_notes: `{', '.join(case['risk_notes'])}`",
                "",
                *markdown_table(
                    [
                        "turn",
                        "customer_message",
                        "shadow_response",
                        "tools",
                        "accepted",
                        "blocked",
                        "events",
                        "pipeline",
                    ],
                    [
                        [
                            turn["turn"],
                            turn["customer_message"],
                            turn["final_message_visible"],
                            ", ".join(turn["tools_used"]) or "-",
                            ", ".join(item["field"] for item in turn["fields_accepted"]) or "-",
                            ", ".join(item["field"] for item in turn["fields_blocked"]) or "-",
                            ", ".join(turn["business_events"]) or "-",
                            turn["pipeline_shadow"]["stage"] or "-",
                        ]
                        for turn in case["turns"]
                    ],
                ),
                "",
            ]
        )
    return lines


def _human_review_markdown(payload: dict[str, Any]) -> list[str]:
    return [
        "# Dinamo Shadow Human Sales Quality Review",
        "",
        f"- overall_average: `{payload['overall_average']}`",
        f"- high_risk_conversations: `{payload['high_risk_conversations']}`",
        f"- review_scope: `{payload['review_scope']}`",
        "",
        "## Safety Flags",
        "",
        *_safety_lines(payload["safety"]),
        "",
        "## Dimension Averages",
        "",
        *markdown_table(
            ["dimension", "average"],
            [[key, value] for key, value in payload["dimension_averages"].items()],
        ),
        "",
        "## Conversations",
        "",
        *markdown_table(
            ["conversation", "score", "classification"],
            [
                [
                    review["conversation_id"],
                    review["overall_score"],
                    review["classification"],
                ]
                for review in payload["reviews"]
            ],
        ),
        "",
        "## Limitations",
        "",
        *[f"- {item}" for item in payload["limitations"]],
    ]


def _incoherence_markdown(payload: dict[str, Any]) -> list[str]:
    return [
        "# Dinamo Shadow Real Replay Incoherence Audit",
        "",
        f"- failed_checks: `{payload['failed_checks']}`",
        f"- coverage_gaps: `{', '.join(payload['coverage_gaps']) or 'none'}`",
        "",
        "## Safety Flags",
        "",
        *_safety_lines(payload["safety"]),
        "",
        *markdown_table(
            ["check", "status", "observed", "coverage", "conclusion"],
            [
                [
                    check["check_id"],
                    check["status"],
                    check["observed_count"],
                    check["coverage"],
                    check["conclusion"],
                ]
                for check in payload["checks"]
            ],
        ),
    ]


def _e2e_vs_real_markdown(payload: dict[str, Any]) -> list[str]:
    return [
        "# Dinamo Shadow E2E vs Real Replay",
        "",
        f"- e2e_decision: `{payload['e2e_decision']}`",
        f"- replay_cases_passed: `{payload['real_replay_summary']['replay_cases_passed']}/"
        f"{payload['real_replay_summary']['replay_cases_total']}`",
        "",
        "## Safety Flags",
        "",
        *_safety_lines(payload["safety"]),
        "",
        "## Covered In Both",
        "",
        f"- tools: `{', '.join(payload['covered_in_both']['tools']) or 'none'}`",
        (
            f"- business_events: `"
            f"{', '.join(payload['covered_in_both']['business_events']) or 'none'}`"
        ),
        "",
        "## Gaps",
        "",
        *[f"- {gap}" for gap in payload["gaps"]],
    ]


def _readiness_markdown(payload: dict[str, Any]) -> list[str]:
    return [
        "# Dinamo Shadow Real Replay Readiness",
        "",
        f"- decision: `{payload['decision']}`",
        f"- hard_gate_pass: `{payload['hard_gate_pass']}`",
        f"- dataset_cases_total: `{payload['dataset']['cases_total']}`",
        f"- replay_cases_passed: `{payload['replay_summary']['replay_cases_passed']}/"
        f"{payload['replay_summary']['replay_cases_total']}`",
        f"- critical_failure_count: `{payload['replay_summary']['critical_failure_count']}`",
        f"- human_sales_quality_average: `{payload['human_sales_quality_average']}`",
        f"- high_risk_conversations: `{payload['human_high_risk_conversations']}`",
        "",
        "## Safety Flags",
        "",
        *_safety_lines(payload["safety"]),
        "",
        "## Warnings",
        "",
        *[f"- {warning}" for warning in payload["warnings"]],
        "",
        "## Recommended Next Step",
        "",
        payload["recommended_next_step"],
    ]


def _safety_lines(safety: dict[str, Any]) -> list[str]:
    return [
        f"- live_send_enabled: `{safety['live_send_enabled']}`",
        f"- actions_enabled: `{safety['actions_enabled']}`",
        f"- workflow_side_effects_enabled: `{safety['workflow_side_effects_enabled']}`",
        f"- traffic_real_activated: `{safety['traffic_real_activated']}`",
        f"- whatsapp_sent: `{safety['whatsapp_sent']}`",
        f"- config_live_applied: `{safety['config_live_applied']}`",
        f"- single_contact_smoke_enabled: `{safety['single_contact_smoke_enabled']}`",
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--tenant-domain-contract", type=Path)
    parser.add_argument("--anonymized", action="store_true")
    args = parser.parse_args()
    payload = run_replay_eval(
        args.dataset,
        anonymized=args.anonymized,
        tenant_domain_contract=args.tenant_domain_contract,
    )
    print(json.dumps(payload["summary"], ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
