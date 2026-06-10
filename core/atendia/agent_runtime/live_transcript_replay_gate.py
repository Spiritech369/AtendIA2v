from __future__ import annotations

import json
from typing import Any

FORBIDDEN_COPY = [
    "field_not_visible",
    "StateWriter",
    "campo no esta visible",
    "campo no está visible",
    "no puedo registrar",
    "necesito que una persona del equipo revise esto",
    "persona del equipo revise esto",
    "he actualizado tu antig",
    "necesito consultar los requisitos vigentes",
    "si tienes otra consulta",
    "aqui estoy",
    "aquí estoy",
    "hola, en que puedo ayudarte hoy",
    "hola, ¿en que puedo ayudarte hoy",
    "solicitud esta siendo revisada",
    "solicitud está siendo revisada",
    "te responderan pronto",
    "te responderán pronto",
    "json",
    "trace",
    "tool",
    "pending_slot",
    "internal",
    "runtime",
    "error tecnico",
    "error técnico",
]


def gate_audit(turns: list[dict[str, Any]], result: dict[str, Any]) -> dict[str, Any]:
    failures: list[str] = []
    if result.get("run_status") != "passed":
        failures.append(f"test_lab_run_not_passed:{result.get('run_decision')}")
    if (result.get("db_audit_after") or {}).get("outbound_outbox_pending_retry") != 0:
        failures.append("outbound_outbox_pending_retry_not_zero")
    if (result.get("db_audit_after") or {}).get("business_event_ledger_side_effects_allowed") != 0:
        failures.append("side_effects_allowed_not_zero")
    if len(turns) != 18:
        failures.append(f"turn_count_mismatch:{len(turns)}")
    for turn in turns:
        number = turn.get("turn_number")
        final_message = fold(turn.get("final_message"))
        if turn.get("send_decision") != "no_send":
            failures.append(f"send_decision_not_no_send:turn_{number}")
        for phrase in FORBIDDEN_COPY:
            if fold(phrase) in final_message:
                failures.append(f"forbidden_copy:turn_{number}:{phrase}")
        if mentions_price(final_message) and "quote.resolve" not in tools(turn):
            failures.append(f"quote_without_quote_resolve:turn_{number}")
        if mentions_requirements(final_message) and "requirements.lookup" not in tools(turn):
            failures.append(f"requirements_without_requirements_lookup:turn_{number}")
    flow_assertions(turns, failures)
    return {"status": "passed" if not failures else "failed", "failures": failures}


def flow_assertions(turns: list[dict[str, Any]], failures: list[str]) -> None:
    if len(turns) < 18:
        return
    first_two = " ".join(fold(turn.get("final_message")) for turn in turns[:2])
    if "ingreso" in first_two and not any(token in first_two for token in ("tiempo", "antig")):
        failures.append("income_asked_before_seniority")
    if "employment_seniority" not in writes(turns[2]):
        failures.append("fifteen_months_not_written")
    if "ingreso" not in fold(turns[2].get("final_message")):
        failures.append("fifteen_months_did_not_advance_to_income")
    if (
        "product_selection" in pending_after(turns[7])
        and "income_type" not in known_income(turns[7])
    ):
        failures.append("frustration_switched_to_model_when_income_missing")
    if "employment_seniority" not in writes(turns[8]):
        failures.append("ten_months_correction_not_written")
    if mentions_price(fold(turns[13].get("final_message"))):
        failures.append("merchant_quoted_without_sat_clarification")
    if (
        "requirements.lookup" in tools(turns[15])
        and "business_tax_status" in pending_after(turns[15])
    ):
        failures.append("requirements_called_before_merchant_clarification")
    if (
        "recibo" in fold(turns[16].get("final_message"))
        and "business_tax_status" in pending_after(turns[16])
    ):
        failures.append("merchant_received_payroll_requirements")


def replay_decision(result: dict[str, Any]) -> str:
    failures = (result.get("gate_audit") or {}).get("failures") or []
    if not failures:
        return "LIVE_TRANSCRIPT_REPLAY_GATE_PASSED_READY_FOR_APPROVAL_PACKET"
    joined = " ".join(failures)
    if "forbidden_copy" in joined:
        return "LIVE_TRANSCRIPT_REPLAY_BLOCKED_BY_ROBOTIC_COPY"
    if "income_asked_before" in joined or "switched_to_model" in joined:
        return "LIVE_TRANSCRIPT_REPLAY_BLOCKED_BY_FLOW_ORDER"
    if "merchant_quoted" in joined:
        return "LIVE_TRANSCRIPT_REPLAY_BLOCKED_BY_BUSINESS_INCOME_AMBIGUITY"
    if "requirements" in joined or "payroll" in joined:
        return "LIVE_TRANSCRIPT_REPLAY_BLOCKED_BY_REQUIREMENTS_MIX"
    return "LIVE_TRANSCRIPT_REPLAY_BLOCKED_BY_STATE_DRIFT"


def tools(turn: dict[str, Any]) -> set[str]:
    return {
        str(item.get("tool_name") or item.get("tool_id"))
        for item in turn.get("tool_results") or []
        if isinstance(item, dict)
    }


def writes(turn: dict[str, Any]) -> set[str]:
    return {
        str(item.get("field_key") or item.get("field") or item.get("key"))
        for item in turn.get("state_writes") or []
        if isinstance(item, dict)
    }


def pending_after(turn: dict[str, Any]) -> str:
    return str(turn.get("pending_slot_after") or turn.get("pending_slot") or "")


def known_income(turn: dict[str, Any]) -> str:
    state = turn.get("state_after") if isinstance(turn.get("state_after"), dict) else {}
    return json.dumps(state, ensure_ascii=False)


def mentions_price(text: str) -> bool:
    return any(token in text for token in ("$", "enganche", "quincen", "mensualidad", "pago"))


def mentions_requirements(text: str) -> bool:
    return any(
        token in text
        for token in ("ine", "domicilio", "recibo", "estado de cuenta", "papel")
    )


def fold(value: Any) -> str:
    return (
        str(value or "")
        .casefold()
        .replace("á", "a")
        .replace("é", "e")
        .replace("í", "i")
        .replace("ó", "o")
        .replace("ú", "u")
        .replace("ñ", "n")
    )


def printable_turns(turns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "turn_number": turn.get("turn_number"),
            "inbound": turn.get("inbound"),
            "final_message": turn.get("final_message"),
            "send_decision": turn.get("send_decision"),
            "tools": sorted(tools(turn)),
            "writes": sorted(writes(turn)),
        }
        for turn in turns
    ]
