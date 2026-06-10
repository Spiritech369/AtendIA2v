from __future__ import annotations

# ruff: noqa: E402,I001

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
CORE_DIR = REPO_ROOT / "core"
TOOLS_DIR = REPO_ROOT / "tools"
for path in (CORE_DIR, TOOLS_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from run_real_agent_test_lab_no_send_2026_06_07 import (
    _audit,
    _ensure_product_agent_bindings,
    _select_or_seed_version,
)
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from atendia.config import get_settings
from atendia.product_agents import service, test_lab

APPROVED_TENANT_ID = "6ad78236-1fc9-467a-858d-90d248d57ee5"
APPROVED_AGENT_ID = "c169deec-226d-55b7-bd07-270f339e75a6"

os.environ.setdefault("ATENDIA_V2_AGENT_RUNTIME_V2_SEND_ENABLED", "false")
os.environ.setdefault("ATENDIA_V2_AGENT_RUNTIME_V2_ACTIONS_ENABLED", "false")
os.environ.setdefault("ATENDIA_V2_AGENT_RUNTIME_V2_WORKFLOW_EVENTS_ENABLED", "false")

REPORT_JSON_PATH = REPO_ROOT / "reports" / "live_transcript_replay_gate_2026_06_09.json"

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

SCENARIO = {
    "name": "LIVE_TRANSCRIPT_REPLAY_GATE real failed WhatsApp transcript 2026-06-09",
    "turns": [
        {"inbound_text": "Hola"},
        {"inbound_text": "Busco info"},
        {"inbound_text": "15 meses"},
        {"inbound_text": "hola"},
        {"inbound_text": "que ocupo_"},
        {"inbound_text": "22 años"},
        {"inbound_text": "hola"},
        {"inbound_text": "ya te dije no?"},
        {"inbound_text": "tengo 10 meses"},
        {"inbound_text": "metro"},
        {"inbound_text": "si quiero saber"},
        {"inbound_text": "que ocupo"},
        {"inbound_text": "Entonces"},
        {"inbound_text": "Soy comerciante"},
        {"inbound_text": "Esta muy caro"},
        {"inbound_text": "Que ocupas"},
        {"inbound_text": "Dime"},
        {"inbound_text": "Eres un robot?"},
    ],
    "expected": {
        "expected_send_decision": "no_send",
        "internal_text_forbidden": True,
        "trace_required": True,
        "final_message_not_contains": FORBIDDEN_COPY,
    },
}


async def main() -> None:
    settings = get_settings()
    result: dict[str, Any] = {
        "send_enabled": bool(settings.agent_runtime_v2_send_enabled),
        "actions_enabled": bool(settings.agent_runtime_v2_actions_enabled),
        "workflow_events_enabled": bool(settings.agent_runtime_v2_workflow_events_enabled),
        "openai_key_present": bool(settings.openai_api_key or os.getenv("OPENAI_API_KEY")),
        "scenario_turns": len(SCENARIO["turns"]),
    }
    if result["send_enabled"] is not False:
        result["decision"] = "LIVE_TRANSCRIPT_REPLAY_UNSAFE_DO_NOT_REACTIVATE"
        result["blocker"] = "SEND_FLAG_NOT_FALSE"
        _write_result(result)
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return

    engine = create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        async with session.begin():
            selected = await _select_or_seed_version(session)
            if selected is None:
                result["decision"] = "LIVE_TRANSCRIPT_REPLAY_BLOCKED_BY_STATE_DRIFT"
                result["blocker"] = "NO_PRODUCT_AGENT_FOUND"
                _write_result(result)
                print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
                return
            tenant_id, agent_id, version_id = selected
            result.update(
                {
                    "tenant_id": str(tenant_id),
                    "agent_id": str(agent_id),
                    "agent_version_id": str(version_id),
                }
            )
            if str(tenant_id) != APPROVED_TENANT_ID or str(agent_id) != APPROVED_AGENT_ID:
                result["decision"] = "LIVE_TRANSCRIPT_REPLAY_UNSAFE_DO_NOT_REACTIVATE"
                result["blocker"] = "TENANT_OR_AGENT_MISMATCH"
                _write_result(result)
                print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
                return
            result["binding_result"] = await _ensure_product_agent_bindings(
                session,
                tenant_id=tenant_id,
                agent_id=agent_id,
                version_id=version_id,
            )
            result["db_audit_before"] = await _audit(session, tenant_id)
            suite = await service.create_agent_test_suite(
                session,
                tenant_id=tenant_id,
                version_id=version_id,
                name="LIVE_TRANSCRIPT_REPLAY_GATE 2026-06-09",
                mode="incident_replay",
                metadata={
                    "created_by": "run_live_transcript_replay_gate_2026_06_09",
                    "live_transcript_replay_gate": True,
                },
            )
            await service.create_agent_test_scenario(
                session,
                tenant_id=tenant_id,
                suite_id=suite.id,
                name=SCENARIO["name"],
                turns=SCENARIO["turns"],
                expected=SCENARIO["expected"],
                metadata={
                    "created_by": "run_live_transcript_replay_gate_2026_06_09",
                    "live_transcript_replay_gate": True,
                },
            )
            run = await test_lab.run_test_suite(
                session,
                tenant_id=tenant_id,
                suite_id=suite.id,
                mode="no_send",
                execution_mode=test_lab.RUNTIME_V2_AGENT_SERVICE_MODE,
                review_required=True,
                created_by_user_id=None,
            )
            result["suite_id"] = str(suite.id)
            result["test_run_id"] = str(run.id)
            result["run_status"] = run.status
            result["run_decision"] = run.decision
            result["scenario_results"] = run.scenario_results
            result["turn_results"] = run.turn_results
            result["trace_ids"] = run.trace_ids
            result["outbox_audit_result"] = run.outbox_audit_result
            result["side_effect_audit_result"] = run.side_effect_audit_result
            result["db_audit_after"] = await _audit(session, tenant_id)
            result["gate_audit"] = _gate_audit(run.turn_results, result)
            result["decision"] = _decision(result)
    await engine.dispose()
    _write_result(result)
    print(json.dumps(_printable(result), ensure_ascii=False, indent=2, default=str))


def _gate_audit(turns: list[dict[str, Any]], result: dict[str, Any]) -> dict[str, Any]:
    failures: list[str] = []
    if result.get("run_status") != "passed":
        failures.append(f"test_lab_run_not_passed:{result.get('run_decision')}")
    if (result.get("db_audit_after") or {}).get("outbound_outbox_pending_retry") != 0:
        failures.append("outbound_outbox_pending_retry_not_zero")
    if (result.get("db_audit_after") or {}).get("business_event_ledger_side_effects_allowed") != 0:
        failures.append("side_effects_allowed_not_zero")
    if len(turns) != len(SCENARIO["turns"]):
        failures.append(f"turn_count_mismatch:{len(turns)}")
    for turn in turns:
        number = turn.get("turn_number")
        final_message = _fold(turn.get("final_message"))
        if turn.get("send_decision") != "no_send":
            failures.append(f"send_decision_not_no_send:turn_{number}")
        for phrase in FORBIDDEN_COPY:
            if _fold(phrase) in final_message:
                failures.append(f"forbidden_copy:turn_{number}:{phrase}")
        if _mentions_price(final_message) and "quote.resolve" not in _tools(turn):
            failures.append(f"quote_without_quote_resolve:turn_{number}")
        if _mentions_requirements(final_message) and "requirements.lookup" not in _tools(turn):
            failures.append(f"requirements_without_requirements_lookup:turn_{number}")
    _flow_assertions(turns, failures)
    return {"status": "passed" if not failures else "failed", "failures": failures}


def _flow_assertions(turns: list[dict[str, Any]], failures: list[str]) -> None:
    if len(turns) < 18:
        return
    first_two = " ".join(_fold(turn.get("final_message")) for turn in turns[:2])
    if "ingreso" in first_two and not any(token in first_two for token in ("tiempo", "antig")):
        failures.append("income_asked_before_seniority")
    if "employment_seniority" not in _writes(turns[2]):
        failures.append("fifteen_months_not_written")
    if "ingreso" not in _fold(turns[2].get("final_message")):
        failures.append("fifteen_months_did_not_advance_to_income")
    if (
        "product_selection" in _pending_after(turns[7])
        and "income_type" not in _known_income(turns[7])
    ):
        failures.append("frustration_switched_to_model_when_income_missing")
    if "employment_seniority" not in _writes(turns[8]):
        failures.append("ten_months_correction_not_written")
    if _mentions_price(_fold(turns[13].get("final_message"))):
        failures.append("merchant_quoted_without_sat_clarification")
    if (
        "requirements.lookup" in _tools(turns[15])
        and "business_tax_status" in _pending_after(turns[15])
    ):
        failures.append("requirements_called_before_merchant_clarification")
    if (
        "recibo" in _fold(turns[16].get("final_message"))
        and "business_tax_status" in _pending_after(turns[16])
    ):
        failures.append("merchant_received_payroll_requirements")


def _decision(result: dict[str, Any]) -> str:
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


def _tools(turn: dict[str, Any]) -> set[str]:
    return {
        str(item.get("tool_name") or item.get("tool_id"))
        for item in turn.get("tool_results") or []
        if isinstance(item, dict)
    }


def _writes(turn: dict[str, Any]) -> set[str]:
    return {
        str(item.get("field_key") or item.get("field") or item.get("key"))
        for item in turn.get("state_writes") or []
        if isinstance(item, dict)
    }


def _pending_after(turn: dict[str, Any]) -> str:
    return str(turn.get("pending_slot_after") or turn.get("pending_slot") or "")


def _known_income(turn: dict[str, Any]) -> str:
    state = turn.get("state_after") if isinstance(turn.get("state_after"), dict) else {}
    return json.dumps(state, ensure_ascii=False)


def _mentions_price(text: str) -> bool:
    return any(token in text for token in ("$", "enganche", "quincen", "mensualidad", "pago"))


def _mentions_requirements(text: str) -> bool:
    return any(
        token in text
        for token in ("ine", "domicilio", "recibo", "estado de cuenta", "papel")
    )


def _fold(value: Any) -> str:
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


def _write_result(result: dict[str, Any]) -> None:
    REPORT_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_JSON_PATH.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


def _printable(result: dict[str, Any]) -> dict[str, Any]:
    out = dict(result)
    out["turn_results"] = [
        {
            "turn_number": turn.get("turn_number"),
            "inbound": turn.get("inbound"),
            "final_message": turn.get("final_message"),
            "send_decision": turn.get("send_decision"),
            "tools": sorted(_tools(turn)),
            "writes": sorted(_writes(turn)),
        }
        for turn in out.get("turn_results") or []
    ]
    return out


if __name__ == "__main__":
    asyncio.run(main())
