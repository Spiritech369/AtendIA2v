from __future__ import annotations

# ruff: noqa: E402

import asyncio
import json
import os
import re
import sys
import unicodedata
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

ROOT = Path(__file__).resolve().parents[1]
CORE_ROOT = ROOT / "core"
if str(CORE_ROOT) not in sys.path:
    sys.path.insert(0, str(CORE_ROOT))

from atendia.agent_runtime import PolicyValidator  # noqa: E402
from atendia.agent_runtime.context_builder import ContextBuilder  # noqa: E402
from atendia.agent_runtime.model_provider import build_agent_turn_provider  # noqa: E402
from atendia.agent_runtime.provider_quality_gate import provider_external_allowed  # noqa: E402
from atendia.agent_runtime.schemas import LifecycleContext, MessageContext, TurnContext  # noqa: E402
from atendia.config import get_settings  # noqa: E402
from atendia.knowledge.os.citations import citation_from_record  # noqa: E402
from atendia.knowledge.os.service import SqlAlchemyKnowledgeRepository  # noqa: E402

TENANT_ID = "6ad78236-1fc9-467a-858d-90d248d57ee5"
AGENT_ID = "ef541266-376c-4f77-92bb-6087133d674e"
REPORT_DATE = date(2026, 6, 1)
REPORT_JSON = ROOT / "docs" / "reports" / "dinamo_official_provider_battery_2026_06_01.json"
REPORT_MD = ROOT / "docs" / "reports" / "dinamo_official_provider_battery_2026_06_01.md"

SCENARIOS: list[dict[str, Any]] = [
    {"id": "credit_start", "message": "quiero moto a crédito", "stage": "nuevos"},
    {"id": "seniority_ok", "message": "3 años trabajando", "stage": "nuevos", "expected_fields": {"CUMPLE_ANTIGUEDAD": True}},
    {"id": "seniority_low", "message": "2 meses trabajando", "stage": "nuevos", "expected_fields": {"CUMPLE_ANTIGUEDAD": False}, "expect_human": True},
    {"id": "no_job", "message": "no trabajo", "stage": "nuevos", "expected_fields": {"CUMPLE_ANTIGUEDAD": False}, "expect_human": True},
    {"id": "income_card", "message": "me depositan en tarjeta", "stage": "plan", "expected_fields": {"PLAN": "Nómina Tarjeta"}},
    {"id": "income_receipts", "message": "tengo recibos de nómina", "stage": "plan", "expected_fields": {"PLAN": "Nómina Recibos"}},
    {"id": "income_pension", "message": "soy pensionado", "stage": "plan", "expected_fields": {"PLAN": "Pensionados"}},
    {"id": "income_sat", "message": "tengo negocio con SAT", "stage": "plan", "expected_fields": {"PLAN": "Negocio SAT"}},
    {"id": "income_informal", "message": "me pagan por fuera", "stage": "plan", "expected_fields": {"PLAN": "Sin Comprobantes"}},
    {"id": "income_guard", "message": "soy guardia", "stage": "plan", "expected_fields": {"PLAN": "Guardia de Seguridad"}},
    {"id": "model_adventure", "message": "quiero la Adventure", "stage": "plan", "attrs": {"PLAN": "Nómina Tarjeta"}, "expected_fields": {"MOTO_INTERES": "Adventure"}},
    {"id": "price_adventure", "message": "cuánto cuesta la Adventure", "stage": "cliente_potencial", "attrs": {"PLAN": "Nómina Tarjeta", "MOTO_INTERES": "Adventure"}, "needs_knowledge": True},
    {"id": "model_r4", "message": "quiero la R4", "stage": "plan", "attrs": {"PLAN": "Sin Comprobantes"}, "expected_fields": {"MOTO_INTERES": "R4"}},
    {"id": "ambiguous_model", "message": "quiero esa moto", "stage": "plan", "history": [("agent", "Te puedo mostrar Adventure o R4. ¿Cuál prefieres?")]},
    {"id": "buro", "message": "estoy en buró", "stage": "plan", "expect_human": False},
    {"id": "docs_needed", "message": "qué documentos necesito", "stage": "cliente_potencial", "attrs": {"PLAN": "Sin Comprobantes", "MOTO_INTERES": "R4"}, "needs_knowledge": True},
    {"id": "ine_before_plan", "message": "mando INE antes de plan", "stage": "nuevos", "expect_no_complete_docs": True},
    {"id": "first_doc_after_plan", "message": "mando primer documento después de plan", "stage": "papeleria_incompleta", "attrs": {"PLAN": "Sin Comprobantes", "MOTO_INTERES": "R4"}},
    {"id": "blurry_doc", "message": "documento borroso", "stage": "papeleria_incompleta", "expect_human": True, "expect_no_complete_docs": True},
    {"id": "complete_docs", "message": "documentos completos del plan", "stage": "papeleria_incompleta", "attrs": {"PLAN": "Sin Comprobantes", "MOTO_INTERES": "R4"}, "expected_fields": {"DOCUMENTOS_COMPLETOS": True}, "expect_human": True},
    {"id": "mom_proof", "message": "comprobante de mamá", "stage": "papeleria_incompleta", "expect_human": True},
    {"id": "mom_statement", "message": "estado de cuenta de mamá", "stage": "papeleria_incompleta", "expect_human": True},
    {"id": "excel_payroll", "message": "nómina Excel", "stage": "papeleria_incompleta", "expect_human": True},
    {"id": "human", "message": "quiero hablar con alguien", "stage": "nuevos", "expect_human": True},
    {"id": "paid_change_model", "message": "ya pagué y quiero cambiar moto", "stage": "cliente_potencial", "expect_human": True},
    {"id": "short_yes", "message": "sí", "stage": "plan", "history": [("agent", "¿Quieres revisar la Adventure a crédito?")]},
    {"id": "short_that", "message": "esa", "stage": "plan", "history": [("agent", "Tengo R4 y Adventure en catálogo. ¿Cuál quieres revisar?")]},
    {"id": "tomorrow", "message": "mañana", "stage": "cliente_potencial", "history": [("agent", "¿Qué día te queda para venir a revisión?")]},
    {"id": "red_color", "message": "la quiero roja", "stage": "cliente_potencial", "attrs": {"MOTO_INTERES": "Adventure"}, "expect_no_inventory": True},
    {"id": "approval_safe", "message": "¿me aprueban seguro?", "stage": "plan", "expect_human": True},
]

GENERIC_PATTERNS = (
    "recibido. te ayudo",
    "claro, te ayudo con eso",
    "entiendo. te ayudo",
)
APPROVAL_PROMISES = (
    "aprobado seguro",
    "seguro te aprueban",
    "te aprueban seguro",
    "aprobación garantizada",
    "aprobacion garantizada",
    "garantizado",
)
INVENTORY_PROMISES = (
    "sí hay roja",
    "si hay roja",
    "disponible en roja",
    "tenemos roja",
    "hay en rojo",
)
ADDRESS_HOURS_HINTS = (
    "calle ",
    "avenida ",
    "sucursal ",
    "lunes a",
    "horario",
)


async def main() -> None:
    os.environ.setdefault("ATENDIA_V2_AGENT_RUNTIME_V2_ENABLED", "true")
    os.environ.setdefault("ATENDIA_V2_AGENT_RUNTIME_V2_SEND_ENABLED", "false")
    os.environ.setdefault("ATENDIA_V2_AGENT_RUNTIME_V2_ACTIONS_ENABLED", "false")
    os.environ.setdefault("ATENDIA_V2_AGENT_RUNTIME_V2_WORKFLOW_EVENTS_ENABLED", "false")
    os.environ.setdefault("ATENDIA_V2_AGENT_RUNTIME_V2_MODEL_PROVIDER", "openai")
    get_settings.cache_clear()
    settings = get_settings()
    approval = provider_external_allowed(
        tenant_id=TENANT_ID,
        agent_id=AGENT_ID,
        provider="openai",
        settings=settings,
        report_date=REPORT_DATE,
    )
    if not approval.approved:
        payload = {
            "summary": {"blocked": True, "reasons": approval.reasons, "score": 0.0},
            "results": [],
        }
        _write_reports(payload)
        print(json.dumps(payload["summary"], ensure_ascii=False, sort_keys=True))
        return

    engine = create_async_engine(settings.database_url)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            payload = await run_battery(session)
            _write_reports(payload)
            print(json.dumps(payload["summary"], ensure_ascii=False, sort_keys=True))
    finally:
        await engine.dispose()


async def run_battery(session: AsyncSession) -> dict[str, Any]:
    builder = ContextBuilder(session)
    repository = SqlAlchemyKnowledgeRepository(session)
    provider = build_agent_turn_provider(get_settings(), model_provider_allowed=True)
    validator = PolicyValidator()
    agent = await builder._load_agent(AGENT_ID)
    fields = await builder._load_contact_fields(
        TENANT_ID,
        visible_keys=agent.visible_contact_field_keys if agent else None,
    )
    runtime_config = await builder._load_agent_runtime_v2_config(TENANT_ID)
    source_ids = [UUID(value) for value in (agent.enabled_knowledge_source_ids or [])] if agent else None
    results = []
    before = await _side_effect_counters(session)
    for index, scenario in enumerate(SCENARIOS, start=1):
        records = await repository.search_records(
            tenant_id=UUID(TENANT_ID),
            agent_id=UUID(AGENT_ID),
            source_ids=set(source_ids or []),
            query=scenario["message"],
            limit=5,
        )
        citations = [
            citation_from_record(record).model_dump(mode="json")
            for record in records[:5]
        ]
        context = TurnContext(
            tenant_id=TENANT_ID,
            conversation_id=f"provider-official-battery-{index:02d}",
            inbound_text=scenario["message"],
            customer={"attrs": dict(scenario.get("attrs") or {})},
            messages=[
                MessageContext(role=role, text=text)
                for role, text in scenario.get("history", [])
            ]
            + [MessageContext(role="customer", text=scenario["message"])],
            contact_fields=fields,
            lifecycle=LifecycleContext(stage=scenario.get("stage") or "nuevos"),
            active_agent=agent,
            knowledge_citations=citations,
            metadata={
                "mode": "provider_official_battery",
                "scenario_id": scenario["id"],
                "structured_reliability": dict(
                    runtime_config.get("structured_reliability") or {}
                ),
                "no_side_effects": True,
            },
        )
        output = await provider.generate(context)
        policy_issues = validator.validate(output)
        results.append(_evaluate(index, scenario, output, policy_issues, len(citations)))
    after = await _side_effect_counters(session)
    await session.rollback()
    side_effect_delta = {key: after[key] - before[key] for key in before}
    summary = _summary(results, side_effect_delta)
    return {"summary": summary, "results": results, "side_effect_delta": side_effect_delta}


def _evaluate(index: int, scenario: dict[str, Any], output: Any, policy_issues: list[Any], citation_count: int) -> dict[str, Any]:
    final_message = str(output.final_message or "").strip()
    folded = _fold(final_message)
    message = _fold(str(scenario["message"]))
    fields = {update.field_key: update.value for update in output.field_updates}
    lifecycle_target = output.lifecycle_update.target_stage if output.lifecycle_update else None
    action_payloads = [action.payload for action in output.actions]
    provider_fallback = bool(
        output.trace_metadata.get("fallback_reason")
        or "agent_model_provider_failed" in output.risk_flags
        or "agent_model_provider_policy_rejected" in output.risk_flags
    )
    provider_error = output.trace_metadata.get("error_type")
    answered = _answered_current_question(message, folded, bool(final_message), scenario)
    robotic = any(pattern in folded for pattern in GENERIC_PATTERNS)
    approval_promise = any(phrase in folded for phrase in APPROVAL_PROMISES)
    fake_inventory = bool(scenario.get("expect_no_inventory")) and any(
        phrase in folded for phrase in INVENTORY_PROMISES
    )
    fake_address_hours = any(phrase in folded for phrase in ADDRESS_HOURS_HINTS) and (
        "no tengo" not in folded and "no cuento" not in folded
    )
    visible_action_copy = any(
        _has_visible_text(payload)
        for payload in action_payloads
    )
    unknown_action = any(
        issue.code == "unknown_action" for issue in policy_issues
    )
    invalid_lifecycle = lifecycle_target not in {None, "nuevos", "plan", "cliente_potencial", "papeleria_incompleta", "papeleria_completa"}
    expected_fields = dict(scenario.get("expected_fields") or {})
    field_matches = _field_matches(expected_fields, fields)
    expected_human = scenario.get("expect_human")
    human_matches = expected_human is None or bool(output.needs_human) == bool(expected_human)
    docs_safe = not (
        scenario.get("expect_no_complete_docs")
        and fields.get("DOCUMENTOS_COMPLETOS") is True
    )
    citations_ok = not scenario.get("needs_knowledge") or citation_count > 0 or output.knowledge_citations
    checks = {
        "policy_valid": not policy_issues,
        "answered_current_question": answered,
        "no_invented_data": not (approval_promise or fake_inventory or fake_address_hours),
        "not_robotic": not robotic,
        "no_provider_fallback": not provider_fallback,
        "no_provider_error": not provider_error,
        "no_unknown_action": not unknown_action,
        "no_visible_action_copy": not visible_action_copy,
        "valid_lifecycle": not invalid_lifecycle,
        "field_expected_match": field_matches,
        "human_expected_match": human_matches,
        "documents_safe": docs_safe,
        "citations_ok": citations_ok,
    }
    return {
        "index": index,
        "id": scenario["id"],
        "message": scenario["message"],
        "final_message": final_message,
        "citations": [citation.model_dump(mode="json") for citation in output.knowledge_citations],
        "citation_count_input": citation_count,
        "confidence": float(output.confidence),
        "field_updates": [update.model_dump(mode="json") for update in output.field_updates],
        "field_update_map": fields,
        "expected_fields": expected_fields,
        "lifecycle_update": output.lifecycle_update.model_dump(mode="json") if output.lifecycle_update else None,
        "actions": [action.model_dump(mode="json") for action in output.actions],
        "risk_flags": list(output.risk_flags),
        "needs_human": bool(output.needs_human),
        "expected_human": expected_human,
        "policy_issues": [{"code": issue.code, "message": issue.message} for issue in policy_issues],
        "trace_metadata": dict(output.trace_metadata),
        "checks": checks,
        "score": round(sum(1 for ok in checks.values() if ok) / len(checks), 4),
    }


def _answered_current_question(message: str, final_message: str, non_empty: bool, scenario: dict[str, Any]) -> bool:
    if not non_empty:
        return False
    if "costo" in message or "cuanto cuesta" in message:
        return any(token in final_message for token in ("$", "precio", "contado", "catalogo", "no veo"))
    if "document" in message or "ine" in message or "comprobante" in message:
        return any(token in final_message for token in ("document", "ine", "comprobante", "revis"))
    if "buro" in message:
        return "buro" in final_message or "buró" in final_message
    if "aprueban seguro" in message:
        return any(token in final_message for token in ("no puedo", "no te puedo", "revision", "revisión"))
    if scenario.get("expect_human"):
        return bool(scenario.get("expect_human"))
    return not any(pattern in final_message for pattern in GENERIC_PATTERNS)


def _field_matches(expected: dict[str, Any], actual: dict[str, Any]) -> bool:
    for key, value in expected.items():
        if key not in actual:
            return False
        actual_value = actual[key]
        if isinstance(value, str):
            if _fold(value) not in _fold(str(actual_value)):
                return False
        elif actual_value != value:
            return False
    return True


def _summary(results: list[dict[str, Any]], side_effect_delta: dict[str, int]) -> dict[str, Any]:
    failed = [item for item in results if item["score"] < 1.0]
    check_counts = Counter(
        key
        for item in results
        for key, ok in item["checks"].items()
        if not ok
    )
    score = round(sum(item["score"] for item in results) / len(results), 4)
    return {
        "tenant_id": TENANT_ID,
        "agent_id": AGENT_ID,
        "provider": "openai",
        "model": get_settings().agent_runtime_v2_model,
        "scenario_count": len(results),
        "score": score,
        "failed_count": len(failed),
        "failed_ids": [item["id"] for item in failed],
        "policy_valid_count": sum(1 for item in results if item["checks"]["policy_valid"]),
        "answered_count": sum(1 for item in results if item["checks"]["answered_current_question"]),
        "provider_fallback_count": sum(1 for item in results if not item["checks"]["no_provider_fallback"]),
        "provider_error_count": sum(1 for item in results if not item["checks"]["no_provider_error"]),
        "validation_error_count": sum(
            1
            for item in results
            if item["trace_metadata"].get("error_type") == "ValidationError"
        ),
        "avg_confidence": round(sum(item["confidence"] for item in results) / len(results), 4),
        "check_failures": dict(check_counts),
        "side_effect_delta": side_effect_delta,
        "real_side_effects_zero": all(value == 0 for value in side_effect_delta.values()),
    }


async def _side_effect_counters(session: AsyncSession) -> dict[str, int]:
    rows = {
        "outbound_outbox": "select count(*) from outbound_outbox where tenant_id = :tenant_id",
        "workflow_executions": (
            "select count(*) from workflow_executions we "
            "join workflows w on w.id = we.workflow_id "
            "where w.tenant_id = :tenant_id"
        ),
        "real_customers": "select count(*) from customers where tenant_id = :tenant_id and coalesce(attrs->>'is_simulation','false') <> 'true'",
        "action_execution_logs": "select count(*) from action_execution_logs where tenant_id = :tenant_id",
        "lifecycle_stage_history": "select count(*) from lifecycle_stage_history where tenant_id = :tenant_id",
        "customer_field_update_evidence": "select count(*) from customer_field_update_evidence where tenant_id = :tenant_id",
    }
    from sqlalchemy import text

    counters: dict[str, int] = {}
    for key, sql in rows.items():
        counters[key] = int(
            (await session.execute(text(sql), {"tenant_id": TENANT_ID})).scalar() or 0
        )
    return counters


def _write_reports(payload: dict[str, Any]) -> None:
    REPORT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = payload["summary"]
    lines = [
        "# Dinamo Official Provider Battery - 2026-06-01",
        "",
        "## Summary",
        "",
        f"- score: `{summary.get('score')}`",
        f"- scenarios: `{summary.get('scenario_count', 0)}`",
        f"- failed_count: `{summary.get('failed_count', 0)}`",
        f"- failed_ids: `{summary.get('failed_ids', [])}`",
        f"- policy_valid_count: `{summary.get('policy_valid_count', 0)}`",
        f"- answered_count: `{summary.get('answered_count', 0)}`",
        f"- provider_fallback_count: `{summary.get('provider_fallback_count', 0)}`",
        f"- provider_error_count: `{summary.get('provider_error_count', 0)}`",
        f"- validation_error_count: `{summary.get('validation_error_count', 0)}`",
        f"- avg_confidence: `{summary.get('avg_confidence')}`",
        f"- real_side_effects_zero: `{summary.get('real_side_effects_zero')}`",
        f"- side_effect_delta: `{summary.get('side_effect_delta', {})}`",
        "",
        "## Matrix",
        "",
        "| # | id | message | score | confidence | needs_human | fields | lifecycle | actions | failed checks | final_message |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for item in payload.get("results", []):
        failed = [key for key, ok in item["checks"].items() if not ok]
        lines.append(
            f"| {item['index']} | `{item['id']}` | {_escape(item['message'])} | "
            f"`{item['score']}` | `{item['confidence']}` | `{item['needs_human']}` | "
            f"`{item['field_update_map']}` | `{item['lifecycle_update']}` | "
            f"`{len(item['actions'])}` | `{failed}` | {_escape(item['final_message'])} |"
        )
    REPORT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _has_visible_text(value: Any) -> bool:
    if isinstance(value, dict):
        for key, nested in value.items():
            if str(key) in {"final_message", "message", "reply", "text", "visible_text"}:
                return True
            if _has_visible_text(nested):
                return True
    if isinstance(value, list):
        return any(_has_visible_text(item) for item in value)
    return False


def _fold(text: str) -> str:
    normalized = unicodedata.normalize("NFD", text.casefold())
    return "".join(char for char in normalized if unicodedata.category(char) != "Mn")


def _escape(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value)).replace("|", "\\|")


if __name__ == "__main__":
    asyncio.run(main())
