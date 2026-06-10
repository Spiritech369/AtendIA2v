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

os.environ.setdefault("ATENDIA_V2_AGENT_RUNTIME_V2_ENABLED", "true")
os.environ.setdefault("ATENDIA_V2_AGENT_RUNTIME_V2_SEND_ENABLED", "false")
os.environ.setdefault("ATENDIA_V2_AGENT_RUNTIME_V2_ACTIONS_ENABLED", "false")
os.environ.setdefault("ATENDIA_V2_AGENT_RUNTIME_V2_WORKFLOW_EVENTS_ENABLED", "false")

REPORT_JSON_PATH = (
    REPO_ROOT
    / "reports"
    / "controlled_single_contact_smoke_readiness_v2_no_send_result_2026_06_08.json"
)

GENERIC_COPY_FORBIDDEN = [
    "Si se puede revisar; para darte el plan correcto",
    "Sí se puede revisar; para darte el plan correcto",
    "Tomo tu mensaje",
    "reviso el contexto",
    "siguiente paso con el contexto actual",
    "Dime que dato quieres revisar",
    "Dime qué dato quieres revisar",
    "Para cotizarte bien, dime que modelo quieres",
    "Necesito consultar los requisitos vigentes",
]

SCENARIOS: list[dict[str, Any]] = [
    {
        "name": "Critical credit document followup",
        "turns": [
            {
                "inbound_text": (
                    "Hola, vi una Skeleton, cuanto sale a credito? Estoy en buro"
                )
            },
            {"inbound_text": "me pagan por tarjeta"},
            {"inbound_text": "tengo 2 anos"},
            {"inbound_text": "que papeles ocupo"},
            {"inbound_text": "te mando INE al rato"},
            {"inbound_text": "?"},
        ],
        "expected": {
            "expected_send_decision": "no_send",
            "internal_text_forbidden": True,
            "trace_required": True,
            "expected_turns": [
                {
                    "expected_tools": ["catalog.search", "faq.lookup"],
                    "expected_state_writes": ["product_selection"],
                    "final_message_not_contains": GENERIC_COPY_FORBIDDEN,
                },
                {
                    "expected_tools": ["credit_plan.resolve"],
                    "expected_state_writes": [
                        "plan_selection",
                        "down_payment_percent",
                    ],
                    "final_message_not_contains": GENERIC_COPY_FORBIDDEN,
                },
                {
                    "expected_tools": ["quote.resolve"],
                    "expected_state_writes": [
                        "employment_seniority",
                        "quote_snapshot_id",
                    ],
                    "final_message_not_contains": GENERIC_COPY_FORBIDDEN,
                },
                {
                    "expected_tools": ["requirements.lookup"],
                    "expected_state_writes": ["requirements_checklist"],
                    "final_message_not_contains": GENERIC_COPY_FORBIDDEN,
                },
                {
                    "forbidden_state_writes": [
                        "requirements_complete",
                        "Doc_Completos",
                    ],
                    "final_message_not_contains": GENERIC_COPY_FORBIDDEN,
                },
                {
                    "forbidden_state_writes": [
                        "requirements_complete",
                        "Doc_Completos",
                    ],
                    "final_message_not_contains": GENERIC_COPY_FORBIDDEN,
                },
            ],
        },
    },
    {
        "name": "Ambiguous business and model selection",
        "turns": [
            {"inbound_text": "Hola, quiero informacion del credito"},
            {"inbound_text": "Tengo negocio"},
            {"inbound_text": "Vendo comida desde mi casa"},
            {"inbound_text": "No tengo SAT"},
            {"inbound_text": "Quiero algo economico para moverme diario"},
            {"inbound_text": "La Adventure"},
        ],
        "expected": {
            "expected_send_decision": "no_send",
            "internal_text_forbidden": True,
            "trace_required": True,
            "expected_turns": [
                {
                    "forbidden_state_writes": [
                        "plan_selection",
                        "down_payment_percent",
                    ],
                    "final_message_not_contains": GENERIC_COPY_FORBIDDEN,
                },
                {
                    "expected_tools": ["credit_plan.resolve"],
                    "forbidden_state_writes": [
                        "plan_selection",
                        "down_payment_percent",
                    ],
                    "final_message_not_contains": GENERIC_COPY_FORBIDDEN,
                },
                {
                    "forbidden_state_writes": [
                        "plan_selection",
                        "down_payment_percent",
                    ],
                    "final_message_not_contains": GENERIC_COPY_FORBIDDEN,
                },
                {
                    "expected_tools": ["credit_plan.resolve"],
                    "expected_state_writes": [
                        "plan_selection",
                        "down_payment_percent",
                    ],
                    "final_message_not_contains": GENERIC_COPY_FORBIDDEN,
                },
                {
                    "final_message_not_contains": GENERIC_COPY_FORBIDDEN,
                },
                {
                    "expected_tools": ["catalog.search"],
                    "expected_state_writes": ["product_selection"],
                    "final_message_not_contains": GENERIC_COPY_FORBIDDEN,
                },
            ],
        },
    },
]


def _attach_scenario_name(expected: dict[str, Any], scenario_name: str) -> dict[str, Any]:
    expected = dict(expected)
    expected["_scenario_name"] = scenario_name
    per_turn = [dict(item) for item in expected.get("expected_turns") or []]
    for item in per_turn:
        item["_scenario_name"] = scenario_name
    expected["expected_turns"] = per_turn
    return expected


def _readiness_audit(result: dict[str, Any]) -> dict[str, Any]:
    failures: list[str] = []
    turn_results = list(result.get("turn_results") or [])
    if result.get("run_status") != "passed":
        failures.append(f"test_lab_run_not_passed:{result.get('run_decision')}")
    if (result.get("db_audit_after") or {}).get("outbound_outbox_pending_retry") != 0:
        failures.append("outbox_pending_retry_not_zero")
    if (result.get("db_audit_after") or {}).get("business_event_ledger_side_effects_allowed") != 0:
        failures.append("side_effects_allowed_not_zero")
    for key in ("send_enabled", "actions_enabled", "workflow_events_enabled"):
        if result.get(key) is not False:
            failures.append(f"{key}_not_false")
    for turn in turn_results:
        inbound = str(turn.get("inbound") or "")
        final_message = str(turn.get("final_message") or "")
        found = [
            phrase
            for phrase in GENERIC_COPY_FORBIDDEN
            if phrase.casefold() in final_message.casefold()
        ]
        if found:
            failures.append(f"generic_copy_visible:turn_{turn.get('turn_number')}")
        if turn.get("send_decision") != "no_send":
            failures.append(f"send_decision_not_no_send:turn_{turn.get('turn_number')}")
        if not turn.get("trace_id"):
            failures.append(f"trace_missing:turn_{turn.get('turn_number')}")
        if not turn.get("response_plan"):
            failures.append(f"validated_response_plan_missing:turn_{turn.get('turn_number')}")
        composer = turn.get("human_response_composer") or {}
        if not isinstance(composer.get("candidate"), dict) or composer.get("policy_issues"):
            failures.append(f"human_composer_not_clean:turn_{turn.get('turn_number')}")
        if inbound == "te mando INE al rato":
            writes = _written_fields(turn)
            if {"requirements_complete", "Doc_Completos"} & writes:
                failures.append("future_document_marked_complete")
            if any(
                "document.check" == item.get("tool_name")
                for item in turn.get("tool_results") or []
            ):
                failures.append("future_document_ran_document_check_without_attachment")
        if inbound == "?":
            if str(turn.get("message_goal") or "") not in {
                "respond_from_validated_context",
                "acknowledge_future_document_without_state_write",
                "ask_one_clarifying_question_for_pending_slot",
                "explain_validated_requirements",
            }:
                failures.append(f"question_mark_bad_goal:{turn.get('message_goal')}")
    return {
        "status": "passed" if not failures else "failed",
        "failures": failures,
        "checked": [
            "run passed",
            "send/actions/workflow flags false",
            "outbox and side effects zero",
            "no generic visible copy",
            "human composer clean",
            "validated response plan present",
            "future document promise did not mark docs complete",
            "punctuation turn handled without internal copy",
        ],
    }


def _written_fields(turn: dict[str, Any]) -> set[str]:
    return {
        str(item.get("field_key"))
        for item in turn.get("state_writes") or []
        if isinstance(item, dict) and item.get("field_key")
    }


def _token_totals(turn_results: list[dict[str, Any]]) -> dict[str, int]:
    totals = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    for turn in turn_results:
        usage = turn.get("token_usage") or {}
        for key in totals:
            totals[key] += int(usage.get(key) or 0)
    return totals


def _turn_summary(turn_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summary: list[dict[str, Any]] = []
    for turn in turn_results:
        summary.append(
            {
                "scenario": (turn.get("expected") or {}).get("_scenario_name"),
                "turn_number": turn.get("turn_number"),
                "inbound": turn.get("inbound"),
                "final_message": turn.get("final_message"),
                "user_act": turn.get("user_act"),
                "pending_slot": turn.get("pending_slot"),
                "slot_consumed": turn.get("slot_consumed"),
                "message_goal": turn.get("message_goal"),
                "tools": [
                    {
                        "tool_name": item.get("tool_name"),
                        "status": item.get("status"),
                    }
                    for item in turn.get("tool_results") or []
                ],
                "state_writes": sorted(_written_fields(turn)),
                "send_decision": turn.get("send_decision"),
                "trace_id": turn.get("trace_id"),
                "token_usage": turn.get("token_usage") or {},
                "failures": turn.get("failures") or [],
            }
        )
    return summary


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
        "scenario_count": len(SCENARIOS),
    }
    if not key:
        result["decision"] = "READY_FOR_CONTROLLED_SINGLE_CONTACT_SMOKE_BLOCKED_BY_OPENAI_API"
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
                result["decision"] = "READY_FOR_CONTROLLED_SINGLE_CONTACT_SMOKE_BLOCKED_BY_DB"
                result["blocker"] = "NO_PRODUCT_AGENT_FOUND"
                _write_result(result)
                print(json.dumps(_printable(result), ensure_ascii=False, indent=2))
                return

            tenant_id, agent_id, version_id = selected
            result["tenant_id"] = str(tenant_id)
            result["agent_version_id"] = str(version_id)
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
                name="Controlled single-contact smoke readiness V2 no-send 2026-06-08",
                mode="publish_readiness",
                metadata={
                    "created_by": "run_controlled_smoke_readiness_no_send_v2_2026_06_08",
                    "runtime_contract_source": _repo_path(CONTRACT_PATH),
                    "purpose": "READY_FOR_CONTROLLED_SINGLE_CONTACT_SMOKE_APPROVAL_V2",
                },
            )
            for scenario in SCENARIOS:
                await service.create_agent_test_scenario(
                    session,
                    tenant_id=tenant_id,
                    suite_id=suite.id,
                    name=scenario["name"],
                    turns=scenario["turns"],
                    expected=_attach_scenario_name(scenario["expected"], scenario["name"]),
                    metadata={
                        "created_by": (
                            "run_controlled_smoke_readiness_no_send_v2_2026_06_08"
                        )
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


def _decision(result: dict[str, Any]) -> str:
    if result.get("run_status") != "passed":
        return "CONTROLLED_SINGLE_CONTACT_SMOKE_APPROVAL_V2_BLOCKED_BY_TEST_LAB"
    if (result.get("readiness_audit") or {}).get("status") != "passed":
        return "CONTROLLED_SINGLE_CONTACT_SMOKE_APPROVAL_V2_BLOCKED_BY_EVIDENCE"
    if (result.get("db_audit_after") or {}).get("outbound_outbox_pending_retry") != 0:
        return "CONTROLLED_SINGLE_CONTACT_SMOKE_APPROVAL_V2_BLOCKED_BY_DB"
    if (result.get("db_audit_after") or {}).get("business_event_ledger_side_effects_allowed") != 0:
        return "CONTROLLED_SINGLE_CONTACT_SMOKE_APPROVAL_V2_BLOCKED_BY_DB"
    return "READY_FOR_CONTROLLED_SINGLE_CONTACT_SMOKE_APPROVAL_V2"


def _printable(result: dict[str, Any]) -> dict[str, Any]:
    return {
        key: result.get(key)
        for key in (
            "decision",
            "run_status",
            "run_decision",
            "scenario_results",
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
