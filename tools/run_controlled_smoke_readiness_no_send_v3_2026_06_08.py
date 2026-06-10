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
    CONTRACT_PATH,
    _audit,
    _ensure_product_agent_bindings,
    _repo_path,
    _select_or_seed_version,
)
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from atendia.config import get_settings
from atendia.product_agents import service, test_lab

APPROVED_TENANT_ID = "6ad78236-1fc9-467a-858d-90d248d57ee5"
APPROVED_AGENT_ID = "c169deec-226d-55b7-bd07-270f339e75a6"

os.environ.setdefault("ATENDIA_V2_AGENT_RUNTIME_V2_ENABLED", "true")
os.environ.setdefault("ATENDIA_V2_AGENT_RUNTIME_V2_SEND_ENABLED", "false")
os.environ.setdefault("ATENDIA_V2_AGENT_RUNTIME_V2_ACTIONS_ENABLED", "false")
os.environ.setdefault("ATENDIA_V2_AGENT_RUNTIME_V2_WORKFLOW_EVENTS_ENABLED", "false")

REPORT_JSON_PATH = (
    REPO_ROOT
    / "reports"
    / "controlled_single_contact_smoke_v3_preflight_after_internal_leak_fix_result_2026_06_09.json"
)

GENERIC_COPY_FORBIDDEN = [
    "Si se puede revisar; para darte el plan correcto",
    "Sí se puede revisar; para darte el plan correcto",
    "Tomo tu mensaje",
    "reviso el contexto",
    "siguiente paso con el contexto actual",
    "Dime que dato quieres revisar",
    "Dime qué dato quieres revisar",
    "Necesito consultar los requisitos vigentes",
]

SCENARIO = {
    "name": "Controlled smoke V3 seniority-first no-send",
    "turns": [
        {"inbound_text": "hola"},
        {"inbound_text": "info porfavor"},
        {"inbound_text": "tengo 2 años"},
        {"inbound_text": "me pagan por transferencia"},
        {"inbound_text": "?"},
    ],
    "expected": {
        "expected_send_decision": "no_send",
        "internal_text_forbidden": True,
        "trace_required": True,
        "expected_turns": [
            {"final_message_not_contains": GENERIC_COPY_FORBIDDEN},
            {"final_message_not_contains": GENERIC_COPY_FORBIDDEN},
            {
                "expected_state_writes": ["employment_seniority"],
                "final_message_not_contains": GENERIC_COPY_FORBIDDEN,
            },
            {
                "expected_tools": ["credit_plan.resolve"],
                "expected_state_writes": ["plan_selection", "down_payment_percent"],
                "final_message_not_contains": GENERIC_COPY_FORBIDDEN,
            },
            {"final_message_not_contains": GENERIC_COPY_FORBIDDEN},
        ],
    },
}
SCENARIO["turns"][2]["inbound_text"] = "15 meses"


async def main() -> None:
    settings = get_settings()
    key = settings.openai_api_key or os.getenv("OPENAI_API_KEY") or ""
    result: dict[str, Any] = {
        "openai_api_key_present": bool(key),
        "openai_api_key_length": len(key),
        "send_enabled": bool(settings.agent_runtime_v2_send_enabled),
        "actions_enabled": bool(settings.agent_runtime_v2_actions_enabled),
        "workflow_events_enabled": bool(settings.agent_runtime_v2_workflow_events_enabled),
        "model_provider": settings.agent_runtime_v2_model_provider,
        "model": settings.agent_runtime_v2_model,
        "composer_model": settings.composer_model,
        "scenario_count": 1,
    }
    if not key:
        result["decision"] = "SMOKE_V3_BLOCKED_BY_OPENAI_API"
        result["blocker"] = "OPENAI_API_KEY_MISSING"
        _write_result(result)
        print(json.dumps(_printable(result), ensure_ascii=False, indent=2))
        return

    engine = create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        async with session.begin():
            selected = await _select_or_seed_version(session)
            if selected is None:
                result["decision"] = "SMOKE_V3_APPROVAL_BLOCKED_BY_DB_AUDIT"
                result["blocker"] = "NO_PRODUCT_AGENT_FOUND"
                _write_result(result)
                print(json.dumps(_printable(result), ensure_ascii=False, indent=2))
                return

            tenant_id, agent_id, version_id = selected
            result["tenant_id"] = str(tenant_id)
            result["agent_id"] = str(agent_id)
            result["agent_version_id"] = str(version_id)
            if str(tenant_id) != APPROVED_TENANT_ID or str(agent_id) != APPROVED_AGENT_ID:
                result["decision"] = "SMOKE_V3_APPROVAL_BLOCKED_BY_ALLOWLIST"
                result["blocker"] = "PRODUCT_AGENT_TENANT_OR_AGENT_MISMATCH"
                _write_result(result)
                print(json.dumps(_printable(result), ensure_ascii=False, indent=2))
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
                name="Controlled single-contact smoke readiness V3 no-send 2026-06-08",
                mode="publish_readiness",
                metadata={
                    "created_by": "run_controlled_smoke_readiness_no_send_v3_2026_06_08",
                    "runtime_contract_source": _repo_path(CONTRACT_PATH),
                    "purpose": "SMOKE_V3_PREFLIGHT_NO_SEND_AFTER_INTERNAL_LEAK_FIX",
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
                    "created_by": "run_controlled_smoke_readiness_no_send_v3_2026_06_08"
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
            result["turn_summary"] = _turn_summary(run.turn_results)
            result["trace_ids"] = run.trace_ids
            result["outbox_audit_result"] = run.outbox_audit_result
            result["side_effect_audit_result"] = run.side_effect_audit_result
            result["coverage_summary"] = run.coverage_summary
            result["token_totals"] = _token_totals(run.turn_results)
            result["db_audit_after"] = await _audit(session, tenant_id)
            result["readiness_audit"] = _readiness_audit(result)
            result["decision"] = _decision(result)

    await engine.dispose()
    _write_result(result)
    print(json.dumps(_printable(result), ensure_ascii=False, indent=2, default=str))


def _readiness_audit(result: dict[str, Any]) -> dict[str, Any]:
    failures: list[str] = []
    turns = list(result.get("turn_results") or [])
    if result.get("run_status") != "passed":
        failures.append(f"test_lab_run_not_passed:{result.get('run_decision')}")
    if (result.get("db_audit_after") or {}).get("outbound_outbox_pending_retry") != 0:
        failures.append("outbox_pending_retry_not_zero")
    if (result.get("db_audit_after") or {}).get("business_event_ledger_side_effects_allowed") != 0:
        failures.append("side_effects_allowed_not_zero")
    for key in ("send_enabled", "actions_enabled", "workflow_events_enabled"):
        if result.get(key) is not False:
            failures.append(f"{key}_not_false")
    for turn in turns:
        final_message = str(turn.get("final_message") or "")
        if turn.get("send_decision") != "no_send":
            failures.append(f"send_decision_not_no_send:turn_{turn.get('turn_number')}")
        if not turn.get("trace_id"):
            failures.append(f"trace_missing:turn_{turn.get('turn_number')}")
        for phrase in GENERIC_COPY_FORBIDDEN:
            if phrase.casefold() in final_message.casefold():
                failures.append(f"generic_copy_visible:turn_{turn.get('turn_number')}")
        if any(
            token in final_message.casefold()
            for token in ("field_not_visible", "statewriter", "campo no est")
        ):
            failures.append(f"internal_state_writer_text_visible:turn_{turn.get('turn_number')}")
    if len(turns) >= 2:
        early_text = " ".join(str(turn.get("final_message") or "") for turn in turns[:2])
        if "ingreso" in early_text.casefold() and "tiempo" not in early_text.casefold():
            failures.append("income_asked_before_seniority")
        if "tiempo" not in early_text.casefold() and "antig" not in early_text.casefold():
            failures.append("seniority_not_requested_first")
    if len(turns) >= 3 and "employment_seniority" not in _written_fields(turns[2]):
        failures.append("seniority_not_written_after_turn_3")
    if len(turns) >= 4:
        credit_plan_results = [
            item
            for item in turns[3].get("tool_results") or []
            if item.get("tool_name") == "credit_plan.resolve"
        ]
        if not credit_plan_results:
            failures.append("credit_plan_resolve_missing_turn_4")
        elif credit_plan_results[0].get("status") != "succeeded":
            failures.append(
                "credit_plan_resolve_not_succeeded_turn_4:"
                + str((credit_plan_results[0].get("data") or {}).get("reason") or "")
            )
    if len(turns) >= 5:
        final_question_response = str(turns[4].get("final_message") or "")
        folded = final_question_response.casefold()
        has_product = any(
            "product_selection" in _written_fields(turn)
            for turn in turns[:5]
        )
        if not has_product and any(
            token in folded for token in ("cuota", "mensual", "quincenal", "cotiza")
        ):
            failures.append("question_mark_discusses_quote_without_product")
        if not has_product and not any(token in folded for token in ("moto", "modelo")):
            failures.append("question_mark_does_not_resume_missing_model")
    return {
        "status": "passed" if not failures else "failed",
        "failures": failures,
    }


def _decision(result: dict[str, Any]) -> str:
    failures = (result.get("readiness_audit") or {}).get("failures") or []
    if any("source" in str(item) for item in failures):
        return "SMOKE_V3_UNSAFE_DO_NOT_REACTIVATE"
    if any("internal_state_writer_text_visible" in str(item) for item in failures):
        return "SMOKE_V3_BLOCKED_BY_INTERNAL_TEXT_LEAK"
    if any("seniority_not_written_after_turn_3" in str(item) for item in failures):
        return "SMOKE_V3_BLOCKED_BY_STATEWRITER"
    if any(
        str(item)
        in {
            "income_asked_before_seniority",
            "seniority_not_requested_first",
            "question_mark_discusses_quote_without_product",
            "question_mark_does_not_resume_missing_model",
        }
        for item in failures
    ):
        return "SMOKE_V3_BLOCKED_BY_PENDING_SLOT"
    if (result.get("db_audit_after") or {}).get("outbound_outbox_pending_retry") != 0:
        return "SMOKE_V3_UNSAFE_DO_NOT_REACTIVATE"
    if (result.get("db_audit_after") or {}).get("business_event_ledger_side_effects_allowed") != 0:
        return "SMOKE_V3_UNSAFE_DO_NOT_REACTIVATE"
    if result.get("run_status") != "passed":
        return "SMOKE_V3_UNSAFE_DO_NOT_REACTIVATE"
    if (result.get("readiness_audit") or {}).get("status") != "passed":
        return "SMOKE_V3_UNSAFE_DO_NOT_REACTIVATE"
    return "SMOKE_V3_PREFLIGHT_NO_SEND_AFTER_INTERNAL_LEAK_FIX_READY"


def _written_fields(turn: dict[str, Any]) -> set[str]:
    return {
        str(item.get("field_key"))
        for item in turn.get("state_writes") or []
        if isinstance(item, dict) and item.get("field_key")
    }


def _turn_summary(turn_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "turn_number": turn.get("turn_number"),
            "inbound": turn.get("inbound"),
            "final_message": turn.get("final_message"),
            "user_act": turn.get("user_act"),
            "pending_slot": turn.get("pending_slot"),
            "message_goal": turn.get("message_goal"),
            "tools": [
                {"tool_name": item.get("tool_name"), "status": item.get("status")}
                for item in turn.get("tool_results") or []
            ],
            "state_writes": sorted(_written_fields(turn)),
            "send_decision": turn.get("send_decision"),
            "trace_id": turn.get("trace_id"),
            "failures": turn.get("failures") or [],
        }
        for turn in turn_results
    ]


def _token_totals(turn_results: list[dict[str, Any]]) -> dict[str, int]:
    totals = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    for turn in turn_results:
        usage = turn.get("token_usage") or {}
        for key in totals:
            totals[key] += int(usage.get(key) or 0)
    return totals


def _printable(result: dict[str, Any]) -> dict[str, Any]:
    return {
        key: result.get(key)
        for key in (
            "decision",
            "run_status",
            "run_decision",
            "db_audit_before",
            "db_audit_after",
            "readiness_audit",
            "token_totals",
            "suite_id",
            "test_run_id",
        )
        if key in result
    } | {"turn_summary": result.get("turn_summary")}


def _write_result(result: dict[str, Any]) -> None:
    REPORT_JSON_PATH.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    asyncio.run(main())
