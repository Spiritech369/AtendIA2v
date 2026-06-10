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
if str(CORE_DIR) not in sys.path:
    sys.path.insert(0, str(CORE_DIR))

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

os.environ.setdefault("ATENDIA_V2_AGENT_RUNTIME_V2_SEND_ENABLED", "false")
os.environ.setdefault("ATENDIA_V2_AGENT_RUNTIME_V2_ACTIONS_ENABLED", "false")
os.environ.setdefault("ATENDIA_V2_AGENT_RUNTIME_V2_WORKFLOW_EVENTS_ENABLED", "false")


REPORT_JSON_PATH = (
    REPO_ROOT / "reports" / "human_response_composer_no_send_result_2026_06_08.json"
)

GENERIC_COPY_FORBIDDEN = [
    "Si se puede revisar; para darte el plan correcto",
    "Sí se puede revisar; para darte el plan correcto",
    "Tomo tu mensaje",
    "reviso el contexto",
    "siguiente paso con el contexto actual",
    "Dime que dato quieres revisar",
    "Dime qué dato quieres revisar",
]


SCENARIOS: list[dict[str, Any]] = [
    {
        "name": "Pending income greeting guard",
        "turns": [
            {
                "inbound_text": (
                    "Hola, vi una Skeleton, cuanto sale a credito? Estoy en buro"
                )
            },
            {"inbound_text": "hola"},
            {"inbound_text": "ya te dije"},
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
            ],
        },
    },
    {
        "name": "Skeleton buro tarjeta quote requirements",
        "turns": [
            {
                "inbound_text": (
                    "Hola, vi una Skeleton, cuanto sale a credito? Estoy en buro"
                )
            },
            {"inbound_text": "me pagan por tarjeta"},
            {"inbound_text": "tengo 2 anos"},
            {"inbound_text": "que papeles ocupo"},
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
            ],
        },
    },
]


def _composer_audit(turn_results: list[dict[str, Any]]) -> dict[str, Any]:
    failures: list[str] = []
    turns_by_scenario: dict[str, list[dict[str, Any]]] = {}
    for turn in turn_results:
        name = str((turn.get("expected") or {}).get("_scenario_name") or "")
        turns_by_scenario.setdefault(name, []).append(turn)
        final_message = str(turn.get("final_message") or "")
        found = [
            phrase
            for phrase in GENERIC_COPY_FORBIDDEN
            if phrase.casefold() in final_message.casefold()
        ]
        if found:
            failures.append(
                f"generic_copy_visible:turn_{turn.get('turn_number')}:{','.join(found)}"
            )
        composer = turn.get("human_response_composer") or {}
        if not isinstance(composer.get("candidate"), dict) or composer.get("policy_issues"):
            failures.append(f"human_composer_not_succeeded:turn_{turn.get('turn_number')}")
        if not turn.get("response_plan"):
            failures.append(f"validated_response_plan_missing:turn_{turn.get('turn_number')}")

    greeting_turn = None
    for turn in turn_results:
        if turn.get("inbound") == "hola":
            greeting_turn = turn
            break
    if not greeting_turn:
        failures.append("greeting_turn_missing")
    else:
        if greeting_turn.get("user_act") != "greeting":
            failures.append(f"greeting_user_act_mismatch:{greeting_turn.get('user_act')}")
        if greeting_turn.get("slot_consumed") is not False:
            failures.append("greeting_consumed_pending_slot")
        if greeting_turn.get("message_goal") != "greet_and_resume_without_consuming_slot":
            failures.append(
                f"greeting_message_goal_mismatch:{greeting_turn.get('message_goal')}"
            )
        written = {
            item.get("field_key")
            for item in greeting_turn.get("state_writes") or []
            if isinstance(item, dict)
        }
        if {"plan_selection", "down_payment_percent"} & written:
            failures.append("greeting_wrote_income_plan_fields")

    confusion_turn = None
    for turn in turn_results:
        if turn.get("inbound") == "ya te dije":
            confusion_turn = turn
            break
    if not confusion_turn:
        failures.append("confusion_turn_missing")
    else:
        if confusion_turn.get("user_act") not in {"confusion", "frustration"}:
            failures.append(f"confusion_user_act_mismatch:{confusion_turn.get('user_act')}")
        if confusion_turn.get("slot_consumed") is not False:
            failures.append("confusion_consumed_pending_slot")
        written = {
            item.get("field_key")
            for item in confusion_turn.get("state_writes") or []
            if isinstance(item, dict)
        }
        if {"plan_selection", "down_payment_percent"} & written:
            failures.append("confusion_wrote_income_plan_fields")

    return {
        "status": "passed" if not failures else "failed",
        "failures": failures,
        "checked": [
            "generic copy forbidden",
            "human_response_composer trace present",
            "validated_response_plan trace present",
            "greeting does not consume pending_slot",
            "confusion/frustration does not consume pending_slot",
        ],
    }


def _attach_scenario_name(expected: dict[str, Any], scenario_name: str) -> dict[str, Any]:
    expected = dict(expected)
    expected["_scenario_name"] = scenario_name
    per_turn = [dict(item) for item in expected.get("expected_turns") or []]
    for item in per_turn:
        item["_scenario_name"] = scenario_name
    expected["expected_turns"] = per_turn
    return expected


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
        result["decision"] = "HUMAN_RESPONSE_COMPOSER_BLOCKED_BY_OPENAI_API"
        result["blocker"] = "OPENAI_API_KEY_MISSING"
        _write_result(result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    engine = create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        async with session.begin():
            selected = await _select_or_seed_version(session)
            if selected is None:
                result["decision"] = "HUMAN_RESPONSE_COMPOSER_FAILED_BY_DB_AUDIT"
                result["blocker"] = "NO_PRODUCT_AGENT_FOUND"
                _write_result(result)
                print(json.dumps(result, ensure_ascii=False, indent=2))
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
                name="Human Response Composer real no-send evidence 2026-06-08",
                mode="publish_readiness",
                metadata={
                    "created_by": "run_human_response_composer_no_send_2026_06_08",
                    "runtime_contract_source": _repo_path(CONTRACT_PATH),
                    "purpose": "HUMAN_RESPONSE_COMPOSER_FROM_VALIDATED_FACTS",
                },
            )
            for scenario in SCENARIOS:
                await service.create_agent_test_scenario(
                    session,
                    tenant_id=tenant_id,
                    suite_id=suite.id,
                    name=scenario["name"],
                    turns=scenario["turns"],
                    expected=_attach_scenario_name(
                        scenario["expected"],
                        str(scenario["name"]),
                    ),
                    metadata={
                        "created_by": "run_human_response_composer_no_send_2026_06_08"
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
            composer_audit = _composer_audit(run.turn_results)
            result["suite_id"] = str(suite.id)
            result["test_run_id"] = str(run.id)
            result["run_status"] = run.status
            result["run_decision"] = run.decision
            result["scenario_results"] = run.scenario_results
            result["turn_results"] = run.turn_results
            result["trace_ids"] = run.trace_ids
            result["outbox_audit_result"] = run.outbox_audit_result
            result["side_effect_audit_result"] = run.side_effect_audit_result
            result["coverage_summary"] = run.coverage_summary
            result["composer_audit"] = composer_audit
            result["db_audit_after"] = await _audit(session, tenant_id)
            result["decision"] = _decision(result)

    await engine.dispose()
    _write_result(result)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


def _decision(result: dict[str, Any]) -> str:
    if result.get("run_status") != "passed":
        if result.get("run_decision") == test_lab.TEST_LAB_BLOCKED_BY_TOOL:
            return "HUMAN_RESPONSE_COMPOSER_FAILED_BY_REQUIRED_TOOL"
        if result.get("run_decision") == test_lab.TEST_LAB_BLOCKED_BY_POLICY:
            return "HUMAN_RESPONSE_COMPOSER_FAILED_BY_POLICY"
        if result.get("run_decision") == test_lab.REAL_AGENT_TEST_LAB_BLOCKED_BY_OPENAI_API:
            return "HUMAN_RESPONSE_COMPOSER_BLOCKED_BY_OPENAI_API"
        return "HUMAN_RESPONSE_COMPOSER_FAILED_BY_BAD_RESPONSE"
    if (result.get("composer_audit") or {}).get("status") != "passed":
        return "HUMAN_RESPONSE_COMPOSER_FAILED_BY_BAD_RESPONSE"
    if (result.get("db_audit_after") or {}).get("outbound_outbox_pending_retry") != 0:
        return "HUMAN_RESPONSE_COMPOSER_FAILED_BY_DB_AUDIT"
    if (result.get("db_audit_after") or {}).get("business_event_ledger_side_effects_allowed") != 0:
        return "HUMAN_RESPONSE_COMPOSER_FAILED_BY_DB_AUDIT"
    return "HUMAN_RESPONSE_COMPOSER_READY_REAL_NO_SEND_PASSED"


def _write_result(result: dict[str, Any]) -> None:
    REPORT_JSON_PATH.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    asyncio.run(main())
