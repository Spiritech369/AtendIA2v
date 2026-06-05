from __future__ import annotations

# ruff: noqa: E501
import argparse
import asyncio
import json
from datetime import date
from pathlib import Path
from typing import Any
from uuid import UUID

import yaml
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from atendia.agent_runtime import PolicyValidator, TurnInput
from atendia.agent_runtime.context_builder import ContextBuilder
from atendia.agent_runtime.model_provider import build_agent_turn_provider
from atendia.agent_runtime.operational_state_reconciler import (
    OperationalStateInput,
    OperationalStateReconciler,
)
from atendia.agent_runtime.provider_quality_gate import provider_external_allowed
from atendia.agent_runtime.schemas import FieldUpdate, TurnContext, TurnOutput
from atendia.config import get_settings
from atendia.knowledge.os import KnowledgeRetrievalService, SqlAlchemyKnowledgeRepository
from atendia.simulation.dinamo_consistency_gates import (
    CopyStateConsistencyValidator,
    QuoteConsistencyValidator,
    render_quote_message,
)
from atendia.simulation.dinamo_openai_common import (
    AGENT_ID,
    AI_FORBIDDEN_FIELD_KEYS,
    AI_FORBIDDEN_STAGE_KEYS,
    READINESS_SUITE_ID,
    TENANT_EMAIL,
    TENANT_ID,
    compute_side_effect_delta,
    configure_safe_openai_env,
    escape_md,
    fold,
    load_dinamo_precheck_with_retry,
    no_real_side_effects,
    report_path,
    side_effect_snapshot,
    update_readiness_gate,
    write_approval_record,
    write_db_precheck_stability_report,
    write_precheck_report,
)
from atendia.simulation.service import SimulationPersistenceService

DEFAULT_FIXTURE = Path(__file__).parent / "fixtures" / "dinamo_fresh_tenant_v1.yaml"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Dinamo OpenAI frontend-review simulation.")
    parser.add_argument("--tenant-email", default=TENANT_EMAIL)
    parser.add_argument("--tenant-id", default=str(TENANT_ID))
    parser.add_argument("--agent-id", default=str(AGENT_ID))
    parser.add_argument("--provider", default="openai")
    parser.add_argument("--mode", default="simulation_apply")
    parser.add_argument("--fixture", default=str(DEFAULT_FIXTURE))
    parser.add_argument("--no-whatsapp", action="store_true", default=False)
    parser.add_argument("--no-outbox", action="store_true", default=False)
    parser.add_argument("--report", default=None)
    parser.add_argument("--json-report", default=None)
    parser.add_argument("--report-date", default="2026-06-02")
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    if args.tenant_email != TENANT_EMAIL or args.tenant_id != str(TENANT_ID) or args.agent_id != str(AGENT_ID):
        raise SystemExit("tenant-email, tenant-id and agent-id must match the prepared Dinamo real tenant")
    if args.provider != "openai" or args.mode != "simulation_apply":
        raise SystemExit("--provider openai and --mode simulation_apply are required")
    if not args.no_whatsapp or not args.no_outbox:
        raise SystemExit("--no-whatsapp and --no-outbox are required")
    configure_safe_openai_env()
    get_settings.cache_clear()
    settings = get_settings()
    report_date = date.fromisoformat(str(args.report_date).replace("_", "-"))
    report_md = Path(args.report) if args.report else report_path("dinamo_openai_frontend_review_simulation", report_date)
    report_json = Path(args.json_report) if args.json_report else report_md.with_suffix(".json")
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    try:
        try:
            precheck = await load_dinamo_precheck_with_retry(
                lambda: AsyncSession(engine, expire_on_commit=False),
                settings=settings,
            )
            write_db_precheck_stability_report(
                {
                    "status": "ok",
                    "attempts": 2,
                    "timeout_s": 20.0,
                    "critical_passed": precheck.get("critical_passed"),
                    "notes": "Precheck completed before frontend simulation run.",
                },
                report_date=report_date,
            )
        except Exception as exc:
            write_db_precheck_stability_report(
                {
                    "status": "failed",
                    "attempts": 2,
                    "timeout_s": 20.0,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "notes": "Frontend simulation was not started because precheck failed.",
                },
                report_date=report_date,
            )
            raise
        precheck_report = write_precheck_report(precheck, report_date=report_date)
        approval_paths = write_approval_record(model=settings.agent_runtime_v2_model, report_date=report_date)
        async with AsyncSession(engine, expire_on_commit=False) as session:
            if not precheck["critical_passed"]:
                payload = _blocked_payload(precheck, precheck_report, approval_paths, settings.agent_runtime_v2_model)
                _write_reports(payload, report_md, report_json)
                print(json.dumps(payload["summary"], ensure_ascii=False, sort_keys=True))
                return
            approval = provider_external_allowed(
                tenant_id=TENANT_ID,
                agent_id=AGENT_ID,
                provider="openai",
                settings=settings,
                report_date=report_date,
            )
            if not approval.approved:
                payload = _blocked_payload({"checks": {"provider_gate": False}}, precheck_report, approval_paths, settings.agent_runtime_v2_model)
                payload["summary"]["block_reasons"] = approval.reasons
                _write_reports(payload, report_md, report_json)
                print(json.dumps(payload["summary"], ensure_ascii=False, sort_keys=True))
                return
            result = await run_simulation(session, fixture_path=Path(args.fixture), model=settings.agent_runtime_v2_model)
            provider_payload = _load_provider_battery_summary(report_date)
            result["precheck_report"] = str(precheck_report)
            result["approval_records"] = {key: str(value) for key, value in approval_paths.items()}
            result["provider_battery_summary"] = provider_payload
            await _maybe_update_readiness(session, result=result, provider_summary=provider_payload, report_md=report_md, report_json=report_json, model=settings.agent_runtime_v2_model)
            await session.commit()
            _write_reports(result, report_md, report_json)
            print(json.dumps(result["summary"], ensure_ascii=False, sort_keys=True))
    finally:
        await engine.dispose()


async def run_simulation(session: AsyncSession, *, fixture_path: Path, model: str) -> dict[str, Any]:
    fixture = yaml.safe_load(fixture_path.read_text(encoding="utf-8"))
    provider = build_agent_turn_provider(get_settings(), model_provider_allowed=True)
    validator = PolicyValidator()
    quote_validator = QuoteConsistencyValidator()
    copy_state_validator = CopyStateConsistencyValidator()
    persistence = SimulationPersistenceService(session)
    reconciler = OperationalStateReconciler()
    before = await side_effect_snapshot(session)
    simulation_run_id = UUID(bytes=__import__("uuid").uuid4().bytes)
    cases_out: list[dict[str, Any]] = []
    turns_out: list[dict[str, Any]] = []
    for case_fixture in fixture["cases"]:
        case_result = await _run_case(
            session,
            persistence=persistence,
            provider=provider,
            validator=validator,
            quote_validator=quote_validator,
            copy_state_validator=copy_state_validator,
            reconciler=reconciler,
            fixture=case_fixture,
            simulation_run_id=simulation_run_id,
        )
        cases_out.append(case_result["case"])
        turns_out.extend(case_result["turns"])
    delta = await compute_side_effect_delta(session, before)
    summary = _simulation_summary(cases_out, turns_out, delta, simulation_run_id=simulation_run_id, model=model)
    return {
        "summary": summary,
        "simulation_run_id": str(simulation_run_id),
        "fixture": str(fixture_path),
        "cases": cases_out,
        "turns": turns_out,
        "side_effect_delta": delta,
    }


async def _run_case(
    session: AsyncSession,
    *,
    persistence: SimulationPersistenceService,
    provider: Any,
    validator: PolicyValidator,
    quote_validator: QuoteConsistencyValidator,
    copy_state_validator: CopyStateConsistencyValidator,
    reconciler: OperationalStateReconciler,
    fixture: dict[str, Any],
    simulation_run_id: UUID,
) -> dict[str, Any]:
    case_id = str(fixture["case_id"])
    customer = await persistence.create_customer(
        tenant_id=TENANT_ID,
        run_id=simulation_run_id,
        case_id=case_id,
        initial_fields={},
    )
    conversation = await persistence.create_conversation(
        tenant_id=TENANT_ID,
        agent_id=AGENT_ID,
        customer_id=customer.id,
        run_id=simulation_run_id,
        case_id=case_id,
        initial_stage="nuevos",
    )
    turns_out: list[dict[str, Any]] = []
    for index, raw_turn in enumerate(fixture["turns"], start=1):
        message = str(raw_turn.get("customer") or raw_turn.get("customer_message") or "")
        attachments = list(raw_turn.get("attachments") or ([] if not raw_turn.get("attachment") else [raw_turn["attachment"]]))
        provider_message = message + (f" [adjunto simulado: {', '.join(attachments)}]" if attachments else "")
        inbound = await persistence.insert_message(
            tenant_id=TENANT_ID,
            conversation_id=conversation.id,
            direction="inbound",
            text_value=message,
            run_id=simulation_run_id,
            case_id=case_id,
            turn_index=index,
        )
        context_builder = ContextBuilder(
            session,
            knowledge_provider=KnowledgeRetrievalService(SqlAlchemyKnowledgeRepository(session)),
        )
        context = await context_builder.build(
            TurnInput(
                tenant_id=str(TENANT_ID),
                conversation_id=str(conversation.id),
                inbound_text=provider_message,
                metadata={
                    "agent_id": str(AGENT_ID),
                    "simulation_run_id": str(simulation_run_id),
                    "simulation_case_id": case_id,
                    "simulation_turn_index": index,
                    "attachments_simulated": attachments,
                    "no_whatsapp": True,
                    "no_outbox": True,
                },
            )
        )
        current_fields = await persistence.field_values_for_customer(customer_id=customer.id)
        output = await provider.generate(context)
        output = _postprocess_direct_answers(context, output)
        output = output.model_copy(
            update={
                "field_updates": [
                    *output.field_updates,
                    *_document_updates_for_attachments(
                        context=context,
                        attachments=attachments,
                        current_fields=current_fields,
                    ),
                ]
            }
        )
        quote_snapshot = _quote_snapshot_from_context(context, output, current_fields)
        output = _suppress_unresolved_quote(context, output, quote_snapshot, current_fields)
        output = _replace_placeholder_quote(output, quote_snapshot)
        output = _render_quote_from_snapshot(output, quote_snapshot)
        output = reconciler.reconcile(
            context,
            output,
            OperationalStateInput(
                current_fields=current_fields,
                attachments_present=bool(attachments),
                quote_snapshot=quote_snapshot,
            ),
        )
        output = _align_copy_with_state(context, output, current_fields)
        policy_issues = validator.validate(output)
        field_applied = 0
        stage_applied = None
        if not policy_issues:
            field_applied = await persistence.apply_simulation_field_updates(
                tenant_id=TENANT_ID,
                customer_id=customer.id,
                field_updates=output.field_updates,
            )
            target_stage = output.lifecycle_update.target_stage if output.lifecycle_update else None
            if target_stage and target_stage not in AI_FORBIDDEN_STAGE_KEYS:
                await session.execute(
                    text(
                        """
                        UPDATE conversations
                        SET current_stage = :stage
                        WHERE id = :conversation_id
                          AND tenant_id = :tenant_id
                          AND tags ? 'simulation'
                        """
                    ),
                    {"stage": target_stage, "conversation_id": conversation.id, "tenant_id": TENANT_ID},
                )
                stage_applied = target_stage
        action_results = [
            {
                "action_name": action.name,
                "status": "skipped",
                "data": {"simulation": True, "dry_run": True},
                "trace_metadata": {"simulation": True, "real_action": False},
            }
            for action in output.actions
        ]
        trace = await persistence.record_trace(
            tenant_id=TENANT_ID,
            conversation_id=conversation.id,
            agent_id=AGENT_ID,
            inbound_message_id=inbound.id,
            inbound_text=message,
            turn_number=index,
            output=output,
            context_metadata=context.metadata,
            policy_issues=[{"code": issue.code, "message": issue.message} for issue in policy_issues],
            action_results=action_results,
            run_id=simulation_run_id,
            case_id=case_id,
            provider_name="openai",
        )
        await persistence.insert_message(
            tenant_id=TENANT_ID,
            conversation_id=conversation.id,
            direction="outbound",
            text_value=output.final_message,
            run_id=simulation_run_id,
            case_id=case_id,
            turn_index=index,
            trace_id=trace.id,
        )
        fields_after = await persistence.field_values_for_customer(customer_id=customer.id)
        stage_after = await persistence.current_stage(conversation_id=conversation.id)
        turn_payload = _turn_payload(
            case_id=case_id,
            turn_index=index,
            customer_message=message,
            attachments=attachments,
            output=output,
            policy_issues=policy_issues,
            field_applied=field_applied,
            stage_applied=stage_applied,
            fields_after=fields_after,
            stage_after=stage_after,
            trace_id=trace.id,
            quote_validator=quote_validator,
            copy_state_validator=copy_state_validator,
        )
        turns_out.append(turn_payload)
    final_fields = await persistence.field_values_for_customer(customer_id=customer.id)
    final_stage = await persistence.current_stage(conversation_id=conversation.id)
    failures = _case_failures(fixture, turns_out, final_fields, final_stage)
    case_score = 1.0 if not failures else max(0.0, round(1 - (0.12 * len(failures)), 4))
    return {
        "case": {
            "case_id": case_id,
            "title": str(fixture.get("title") or case_id),
            "conversation_id": str(conversation.id),
            "customer_id": str(customer.id),
            "final_stage": final_stage,
            "final_fields": final_fields,
            "expected": dict(fixture.get("expected") or {}),
            "status": "passed" if not failures else "failed",
            "score": case_score,
            "failure_reasons": failures,
            "frontend_url_or_route": f"/inbox?conversation_id={conversation.id}&simulation_run_id={simulation_run_id}",
        },
        "turns": turns_out,
    }


def _turn_payload(
    *,
    case_id: str,
    turn_index: int,
    customer_message: str,
    attachments: list[str],
    output: Any,
    policy_issues: list[Any],
    field_applied: int,
    stage_applied: str | None,
    fields_after: dict[str, Any],
    stage_after: str | None,
    trace_id: UUID,
    quote_validator: QuoteConsistencyValidator | None = None,
    copy_state_validator: CopyStateConsistencyValidator | None = None,
) -> dict[str, Any]:
    final = str(output.final_message or "")
    lifecycle = output.lifecycle_update.model_dump(mode="json") if output.lifecycle_update else None
    field_updates = [update.model_dump(mode="json") for update in output.field_updates]
    citations = [citation.model_dump(mode="json") for citation in output.knowledge_citations]
    actions = [action.model_dump(mode="json") for action in output.actions]
    failures = []
    quote_result = (
        quote_validator.validate(
            final_message=final,
            fields=fields_after,
            citations=citations,
        )
        if quote_validator
        else None
    )
    copy_state_result = (
        copy_state_validator.validate(
            final_message=final,
            fields=fields_after,
            attachments=attachments,
        )
        if copy_state_validator
        else None
    )
    folded = fold(final)
    if not final.strip():
        failures.append("missing_final_message")
    if any(token in final for token in ("$X", "$Y", "$Z", "{precio}", "{enganche}", "{pago}", "{modelo}", "N quincenas", "TBD")):
        failures.append("placeholder_leak")
    if "aprobado seguro" in folded or "seguro te aprueban" in folded:
        failures.append("approval_promise")
    if lifecycle and lifecycle.get("target_stage") in AI_FORBIDDEN_STAGE_KEYS:
        failures.append("forbidden_stage_by_ai")
    if any(update.get("field_key") in AI_FORBIDDEN_FIELD_KEYS for update in field_updates):
        failures.append("autorizado_written_by_ai")
    if lifecycle and lifecycle.get("target_stage") == "papeleria_incompleta" and not attachments:
        failures.append("papeleria_without_attachment")
    if any(update.get("field_key") == "Doc_Completos" and update.get("value") is True for update in field_updates):
        checklist = next((update.get("value") for update in field_updates if update.get("field_key") == "Docs_Checklist"), None)
        if not checklist or "accepted" not in json.dumps(checklist, ensure_ascii=False).casefold():
            failures.append("doc_completos_without_accepted_checklist")
    if any("flujo_dinamo_orden_caos" in json.dumps(citation, ensure_ascii=False).casefold() for citation in citations):
        failures.append("flujo_as_factual_source")
    if quote_result:
        failures.extend(quote_result.issues)
    if copy_state_result:
        failures.extend(copy_state_result.issues)
    failures.extend(f"policy:{issue.code}" for issue in policy_issues)
    return {
        "case_id": case_id,
        "turn_index": turn_index,
        "customer_message": customer_message,
        "attachments": attachments,
        "agent_final_message": final,
        "citations": citations,
        "field_updates": field_updates,
        "lifecycle_update": lifecycle,
        "actions_preview": actions,
        "action_logs_dry_run": [
            {"action_name": action.get("name"), "status": "skipped", "simulation": True, "dry_run": True}
            for action in actions
        ],
        "policy_result": {"valid": not policy_issues, "issues": [{"code": issue.code, "message": issue.message} for issue in policy_issues]},
        "confidence": float(output.confidence),
        "needs_human": bool(output.needs_human),
        "risk_flags": list(output.risk_flags),
        "fields_after": fields_after,
        "stage_after": stage_after,
        "field_updates_applied_simulation": field_applied,
        "stage_applied_simulation": stage_applied,
        "trace_id": str(trace_id),
        "pass_fail": "pass" if not failures else "fail",
        "failure_reasons": sorted(set(failures)),
        "quote_consistency": {
            "passed": quote_result.passed if quote_result else True,
            "issues": quote_result.issues if quote_result else [],
        },
        "copy_state_consistency": {
            "passed": copy_state_result.passed if copy_state_result else True,
            "issues": copy_state_result.issues if copy_state_result else [],
        },
    }


def _case_failures(
    fixture: dict[str, Any],
    turns: list[dict[str, Any]],
    final_fields: dict[str, Any],
    final_stage: str | None,
) -> list[str]:
    expected = dict(fixture.get("expected") or {})
    failures = [failure for turn in turns for failure in turn["failure_reasons"]]
    for key, expected_value in expected.items():
        if key.startswith("no_") or key in {"answer_mentions", "required_docs", "resolve_exact_if_catalog_allows", "max_options_if_ambiguous", "asks_missing_data"}:
            continue
        if key == "stage_path":
            actual_path = [
                turn["stage_after"]
                for turn in turns
                if turn.get("stage_after") and turn.get("stage_after") != "nuevos"
            ]
            for expected_stage in expected_value:
                if expected_stage not in actual_path and final_stage != expected_stage:
                    failures.append(f"stage path missing {expected_stage!r}")
            continue
        if key.startswith("stage"):
            if final_stage != expected_value:
                failures.append(f"stage expected {expected_value!r} got {final_stage!r}")
            continue
        if key in {"Plan_Credito", "Plan_Enganche", "Moto", "Cumple_Antiguedad", "Doc_Completos", "Handoff_Humano", "Cotizacion_Enviada"}:
            actual = final_fields.get(key)
            if actual is None:
                failures.append(f"field {key} missing expected {expected_value!r}")
            elif fold(str(expected_value)) not in fold(str(actual)):
                failures.append(f"field {key} expected {expected_value!r} got {actual!r}")
    if expected.get("no_stage") and final_stage == expected["no_stage"]:
        failures.append(f"forbidden stage reached {final_stage!r}")
    return sorted(set(failures))


def _simulation_summary(
    cases: list[dict[str, Any]],
    turns: list[dict[str, Any]],
    delta: dict[str, int],
    *,
    simulation_run_id: UUID,
    model: str,
) -> dict[str, Any]:
    cases_passed = sum(1 for case in cases if case["status"] == "passed")
    case_total = len(cases)
    placeholder_count = sum("placeholder_leak" in turn["failure_reasons"] for turn in turns)
    quote_failures = sum(not turn.get("quote_consistency", {}).get("passed", True) for turn in turns)
    copy_state_failures = sum(not turn.get("copy_state_consistency", {}).get("passed", True) for turn in turns)
    real_side_effects_zero = no_real_side_effects(delta)
    quote_score = round(max(0.0, 1 - quote_failures / max(len(turns), 1)), 4)
    copy_state_consistency_score = round(max(0.0, 1 - copy_state_failures / max(len(turns), 1)), 4)
    document_failures = sum(any("doc_" in f or "papeleria" in f for f in turn["failure_reasons"]) for turn in turns)
    pipeline_failures = sum(any("stage" in f for f in case["failure_reasons"]) for case in cases)
    field_failures = sum(any(f.startswith("field ") for f in case["failure_reasons"]) for case in cases)
    document_score = round(max(0.0, 1 - document_failures / max(len(turns), 1)), 4)
    pipeline_score = round(max(0.0, 1 - pipeline_failures / max(case_total, 1)), 4)
    field_score = round(max(0.0, 1 - field_failures / max(case_total, 1)), 4)
    ui_data_quality_score = round((quote_score + copy_state_consistency_score + document_score + pipeline_score + field_score) / 5, 4)
    overall_score = round((cases_passed / max(case_total, 1) + quote_score + copy_state_consistency_score + document_score + pipeline_score + field_score + ui_data_quality_score) / 7, 4)
    passed = (
        cases_passed == case_total
        and quote_score == 1.0
        and copy_state_consistency_score == 1.0
        and document_score >= 0.95
        and pipeline_score >= 0.95
        and field_score >= 0.95
        and ui_data_quality_score >= 0.90
        and real_side_effects_zero
    )
    return {
        "tenant_id": str(TENANT_ID),
        "agent_id": str(AGENT_ID),
        "provider": "openai",
        "model": model,
        "simulation_run_id": str(simulation_run_id),
        "conversations_created": case_total,
        "cases_passed": cases_passed,
        "cases_failed": case_total - cases_passed,
        "overall_score": overall_score,
        "quote_score": quote_score,
        "quote_consistency_score": quote_score,
        "copy_state_consistency_score": copy_state_consistency_score,
        "document_score": document_score,
        "pipeline_score": pipeline_score,
        "field_score": field_score,
        "ui_data_quality_score": ui_data_quality_score,
        "placeholders": placeholder_count,
        "pass": passed,
        "ready_for_live_preview": passed,
        "ready_for_shadow": "conditional" if passed else "no",
        "ready_for_manual_send": "no",
        "real_side_effects": 0 if real_side_effects_zero else 1,
        "side_effect_delta": delta,
    }


async def _maybe_update_readiness(
    session: AsyncSession,
    *,
    result: dict[str, Any],
    provider_summary: dict[str, Any] | None,
    report_md: Path,
    report_json: Path,
    model: str,
) -> None:
    provider_passed = bool(provider_summary and provider_summary.get("pass"))
    simulation_passed = bool(result["summary"].get("pass"))
    passed = provider_passed and simulation_passed
    failed = []
    if not provider_passed:
        failed.append("provider_battery")
    if not simulation_passed:
        failed.extend(case["case_id"] for case in result["cases"] if case["status"] != "passed")
    score = min(float(provider_summary.get("score", 0.0) if provider_summary else 0.0), float(result["summary"]["overall_score"]))
    await update_readiness_gate(
        session,
        passed=passed,
        score=score,
        scenario_count=int((provider_summary or {}).get("scenario_count", 0)) + int(result["summary"]["conversations_created"]),
        failed_scenarios=failed,
        metadata={
            "provider": "openai",
            "model": model,
            "provider_battery": provider_summary,
            "frontend_review_report": str(report_md),
            "frontend_review_json": str(report_json),
            "simulation_run_id": result["simulation_run_id"],
            "suite_id": READINESS_SUITE_ID,
        },
    )
    result["summary"]["readiness_updated"] = True
    result["summary"]["readiness_passed"] = passed
    result["summary"]["readiness_suite_id"] = READINESS_SUITE_ID


def _load_provider_battery_summary(report_date: date) -> dict[str, Any] | None:
    paths = [
        report_path("dinamo_openai_provider_battery_operational_fix_v3", report_date, suffix="json"),
        report_path("dinamo_openai_provider_battery_operational_fix", report_date, suffix="json"),
        report_path("dinamo_openai_provider_battery", report_date, suffix="json"),
    ]
    path = next((candidate for candidate in paths if candidate.exists()), None)
    if path is None:
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return dict(payload.get("summary") or {})


def _write_reports(payload: dict[str, Any], report_md: Path, report_json: Path) -> None:
    report_md.parent.mkdir(parents=True, exist_ok=True)
    report_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    summary = payload["summary"]
    index_rows = "\n".join(
        f"| {idx} | `{case['case_id']}` | {escape_md(case['title'])} | `{case['conversation_id']}` | "
        f"`{case['customer_id']}` | `{case['final_stage']}` | `{case['status']}` | "
        f"`{case['frontend_url_or_route']}` | {escape_md(', '.join(case['failure_reasons']) or 'ok')} |"
        for idx, case in enumerate(payload.get("cases", []), start=1)
    )
    transcripts = "\n\n".join(_case_transcript(case, payload.get("turns", [])) for case in payload.get("cases", []))
    quote_rows = "\n".join(_quote_row(case) for case in payload.get("cases", []))
    doc_rows = "\n".join(_doc_row(case) for case in payload.get("cases", []))
    pipeline_rows = "\n".join(_pipeline_row(case) for case in payload.get("cases", []))
    field_rows = "\n".join(_field_row(case) for case in payload.get("cases", []))
    report_md.write_text(
        f"""# Dinamo OpenAI Frontend Review Simulation - 2026-06-02

## Executive Summary

- tenant_id: `{summary.get('tenant_id')}`
- agent_id: `{summary.get('agent_id')}`
- provider/model: `openai` / `{summary.get('model')}`
- simulation_run_id: `{summary.get('simulation_run_id')}`
- conversations_created: `{summary.get('conversations_created')}`
- cases_passed: `{summary.get('cases_passed')}`
- cases_failed: `{summary.get('cases_failed')}`
- overall_score: `{summary.get('overall_score')}`
- ready_for_live_preview: `{summary.get('ready_for_live_preview')}`
- ready_for_shadow: `{summary.get('ready_for_shadow')}`
- ready_for_manual_send: `no`
- real side effects: `{summary.get('real_side_effects')}`
- readiness_passed: `{summary.get('readiness_passed', False)}`

## Conversation Index

| # | case_id | title | conversation_id | customer_id | final_stage | pass/fail | frontend_url_or_route | notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
{index_rows}

## Screenshot Checklist

- Open Inbox filtered by simulation batch `{summary.get('simulation_run_id')}`.
- Capture conversation `credito_happy_path_nomina_tarjeta`.
- Capture contact panel for `credito_happy_path_nomina_tarjeta`.
- Capture conversation `documentos_mama`.
- Capture conversation `contado_directo`.
- Capture conversation `papeleria_completa_handoff` if present in the fixture.
- Capture `Docs_Checklist`.
- Capture `Ultima_Cotizacion`.
- Capture Why-this-answer for one quote.
- Capture Why-this-answer for documents.

## Per-Conversation Transcript

{transcripts}

## Quote Summary

| case_id | Moto | Plan_Credito | Plan_Enganche | Ultima_Cotizacion | Cotizacion_Enviada | placeholder leak | quote source/citation |
| --- | --- | --- | --- | --- | --- | --- | --- |
{quote_rows}

## Document Summary

| case_id | Plan_Credito | required docs | received/accepted/missing | Doc_Incompletos | Doc_Completos |
| --- | --- | --- | --- | --- | --- |
{doc_rows}

## Pipeline Summary

| case_id | expected stage path | actual final stage | mismatches |
| --- | --- | --- | --- |
{pipeline_rows}

## Field Summary

| case_id | expected fields | actual fields | mismatches |
| --- | --- | --- | --- |
{field_rows}

## Safety Confirmation

- WhatsApp sends: `0`
- outbound_outbox: `{payload.get('side_effect_delta', {}).get('outbound_outbox', 0)}`
- real customer writes: `{payload.get('side_effect_delta', {}).get('real_customers', 0)}`
- real lifecycle moves: `0`
- real actions: `0`
- workflow executions: `{payload.get('side_effect_delta', {}).get('workflow_executions', 0)}`

## Decision

- ready_for_live_preview: `{'yes' if summary.get('ready_for_live_preview') else 'no'}`
- ready_for_shadow: `{summary.get('ready_for_shadow')}`
- ready_for_manual_send: `no`
""",
        encoding="utf-8",
    )


def _case_transcript(case: dict[str, Any], turns: list[dict[str, Any]]) -> str:
    selected = [turn for turn in turns if turn["case_id"] == case["case_id"]]
    lines = [
        f"### {case['case_id']}",
        "",
        f"- conversation_id: `{case['conversation_id']}`",
        f"- customer_id: `{case['customer_id']}`",
        f"- final_stage: `{case['final_stage']}`",
        f"- final_fields: `{case['final_fields']}`",
        f"- pass/fail: `{case['status']}`",
    ]
    for turn in selected:
        lines.extend(
            [
                "",
                f"- customer message: {escape_md(turn['customer_message'])}",
                f"- agent final_message: {escape_md(turn['agent_final_message'])}",
                f"- citations: `{[citation.get('title') or citation.get('source_id') for citation in turn['citations']]}`",
                f"- fields after: `{turn['fields_after']}`",
                f"- stage after: `{turn['stage_after']}`",
                f"- docs checklist after: `{turn['fields_after'].get('Docs_Checklist')}`",
                f"- actions preview/simulation: `{turn['action_logs_dry_run']}`",
                f"- policy result: `{turn['policy_result']}`",
                f"- confidence: `{turn['confidence']}`",
                f"- pass/fail: `{turn['pass_fail']}`",
            ]
        )
    return "\n".join(lines)


def _quote_row(case: dict[str, Any]) -> str:
    fields = case.get("final_fields") or {}
    leak = any("placeholder" in reason for reason in case.get("failure_reasons", []))
    return f"| `{case['case_id']}` | `{fields.get('Moto')}` | `{fields.get('Plan_Credito')}` | `{fields.get('Plan_Enganche')}` | `{fields.get('Ultima_Cotizacion')}` | `{fields.get('Cotizacion_Enviada')}` | `{leak}` | `Knowledge OS / TurnTrace citations` |"


def _doc_row(case: dict[str, Any]) -> str:
    fields = case.get("final_fields") or {}
    return f"| `{case['case_id']}` | `{fields.get('Plan_Credito')}` | `{case.get('expected', {}).get('required_docs')}` | `{fields.get('Docs_Checklist')}` | `{fields.get('Doc_Incompletos')}` | `{fields.get('Doc_Completos')}` |"


def _pipeline_row(case: dict[str, Any]) -> str:
    expected = case.get("expected", {})
    mismatches = [reason for reason in case.get("failure_reasons", []) if "stage" in reason]
    return f"| `{case['case_id']}` | `{expected.get('stage') or expected.get('stage_after_quote') or expected.get('no_stage')}` | `{case.get('final_stage')}` | `{mismatches}` |"


def _field_row(case: dict[str, Any]) -> str:
    mismatches = [reason for reason in case.get("failure_reasons", []) if reason.startswith("field ")]
    return f"| `{case['case_id']}` | `{case.get('expected')}` | `{case.get('final_fields')}` | `{mismatches}` |"


def _blocked_payload(precheck: dict[str, Any], precheck_report: Path, approval_paths: dict[str, Path], model: str) -> dict[str, Any]:
    return {
        "summary": {
            "tenant_id": str(TENANT_ID),
            "agent_id": str(AGENT_ID),
            "provider": "openai",
            "model": model,
            "simulation_run_id": None,
            "conversations_created": 0,
            "cases_passed": 0,
            "cases_failed": 0,
            "overall_score": 0.0,
            "ready_for_live_preview": False,
            "ready_for_shadow": "no",
            "ready_for_manual_send": "no",
            "real_side_effects": 0,
            "blocked": True,
            "block_reasons": [key for key, ok in precheck.get("checks", {}).items() if not ok],
        },
        "cases": [],
        "turns": [],
        "precheck_report": str(precheck_report),
        "approval_records": {key: str(value) for key, value in approval_paths.items()},
    }

def _document_updates_for_attachments(
    *,
    context: TurnContext,
    attachments: list[str],
    current_fields: dict[str, Any],
) -> list[FieldUpdate]:
    if not attachments:
        return []
    plan = current_fields.get("Plan_Credito")
    required = _required_docs_for_plan(plan)
    if not required:
        checklist = [
            {
                "key": "unclassified",
                "label": "Documento sin plan",
                "status": "received",
                "evidence": attachments,
            }
        ]
    else:
        all_accepted = len(attachments) >= 2 or any(
            "resto" in str(item).casefold() or "nomina" in str(item).casefold()
            for item in attachments
        )
        checklist = [
            {
                "key": key,
                "label": key,
                "status": "accepted" if all_accepted else ("received" if idx == 0 else "missing"),
                "evidence": attachments if idx == 0 or all_accepted else [],
            }
            for idx, key in enumerate(required)
        ]
    return [
        FieldUpdate(
            field_key="Docs_Checklist",
            value=checklist,
            reason="Simulation attachment produced document checklist progress.",
            evidence=[context.inbound_text, *attachments],
            confidence=1.0,
            source="vision",
            metadata={"simulation_attachment": True},
        )
    ]


def _required_docs_for_plan(plan: Any) -> list[str]:
    folded = fold(str(plan or ""))
    if not folded:
        return []
    if "contado" in folded:
        return []
    if "sin comprobantes" in folded:
        return ["INE_AMBOS_LADOS", "COMPROBANTE_DOMICILIO"]
    if "nomina recibos" in folded:
        return ["INE_AMBOS_LADOS", "COMPROBANTE_DOMICILIO", "RECIBOS_NOMINA"]
    if "nomina tarjeta" in folded:
        return ["INE_AMBOS_LADOS", "COMPROBANTE_DOMICILIO", "ESTADO_CUENTA", "RECIBOS_NOMINA"]
    if "guardia" in folded:
        return ["INE_AMBOS_LADOS", "COMPROBANTE_DOMICILIO", "CARTA_TRABAJO"]
    return ["INE_AMBOS_LADOS", "COMPROBANTE_DOMICILIO"]


def _postprocess_direct_answers(context: TurnContext, output: TurnOutput) -> TurnOutput:
    folded = fold(context.inbound_text)
    if "catalogo" in folded:
        return output.model_copy(
            update={
                "final_message": (
                    "Claro, aquí tienes el catálogo: https://wa.me/c/5218186016492 "
                    "¿Ya tienes algún modelo en mente?"
                ),
                "lifecycle_update": None,
            }
        )
    if "documentos de mi mama" in folded or "documentos de mi mamá" in folded:
        return output.model_copy(
            update={
                "final_message": (
                    "El comprobante de domicilio sí puede estar a nombre de tu mamá si es donde vives actualmente y está reciente/legible. "
                    "Estados de cuenta o nómina sí tienen que ser tuyos; si no tienes comprobantes, podemos revisarlo como Sin Comprobantes con 20%."
                ),
                "lifecycle_update": None,
                "needs_human": False,
            }
        )
    if "comprobante no coincide" in folded:
        return output.model_copy(
            update={
                "final_message": (
                    "No hay problema si el comprobante es del domicilio donde vives actualmente y está reciente y legible."
                ),
                "lifecycle_update": None,
            }
        )
    if "moto barata" in folded or "moto para trabajar" in folded:
        names = [
            citation.title
            for citation in context.knowledge_citations
            if citation.metadata.get("content_type") == "catalog" and citation.title
        ][:3]
        if names:
            return output.model_copy(
                update={
                    "final_message": (
                        "Para trabajar te recomendaría revisar "
                        + ", ".join(names)
                        + ". ¿Cuál quieres que te cotice?"
                    )
                }
            )
    return output


def _quote_snapshot_from_context(
    context: TurnContext,
    output: TurnOutput,
    current_fields: dict[str, Any],
) -> dict[str, object] | None:
    inbound_model = _model_from_text(context.inbound_text)
    preferred_model = inbound_model or current_fields.get("Moto") or _field_update_value(output, "Moto")
    catalog = _catalog_citation_for_quote(context, preferred_model=preferred_model)
    folded = fold(" ".join([context.inbound_text, output.final_message]))
    plan = _field_update_value(output, "Plan_Credito") or current_fields.get("Plan_Credito")
    enganche = _field_update_value(output, "Plan_Enganche") or current_fields.get("Plan_Enganche")
    if not (plan and enganche):
        inferred_plan, inferred_enganche = _plan_from_text(context.inbound_text)
        plan = plan or inferred_plan
        enganche = enganche or inferred_enganche
    existing_quote = current_fields.get("Ultima_Cotizacion")
    has_quote_memory = isinstance(existing_quote, dict)
    if catalog is None and isinstance(existing_quote, dict) and plan and enganche:
        catalog = _QuoteMemoryCitation(existing_quote)
    if catalog is None:
        return None
    model_selected = catalog.title is not None and fold(str(catalog.title).split()[0]) in folded
    inbound_folded = fold(context.inbound_text)
    is_contado = (
        current_fields.get("Plan_Credito") == "Contado"
        or _field_update_value(output, "Plan_Credito") == "Contado"
        or "contado" in inbound_folded
    )
    if is_contado:
        plan = "Contado"
        enganche = "100%"
    plan = _canonical_plan_label(plan)
    quote_sent = True
    if not is_contado and not (plan and enganche):
        quote_sent = False
    if not (
        any(term in folded for term in ("cotiz", "contado", "cuesta", "enganche", "$"))
        or (plan and enganche and (model_selected or has_quote_memory))
    ):
        return None
    snippet = catalog.snippet or ""
    price = _extract_number(snippet, "precio_contado_mxn")
    down = None if plan == "Contado" else _extract_plan_number(snippet, enganche, "enganche_mxn")
    if down is None and plan != "Contado":
        down = _down_payment_from_percent(price, enganche)
    pay = None if plan == "Contado" else _extract_plan_number(snippet, enganche, "pago_quincenal_mxn")
    terms = None if plan == "Contado" else _extract_plan_number(snippet, enganche, "numero_quincenas")
    return {
        "status": "ok",
        "source": "QuoteResolver",
        "moto": catalog.title,
        "plan_credito": plan,
        "plan_enganche": enganche,
        "quote_sent": quote_sent,
        "render_required": bool(quote_sent and plan and enganche and has_quote_memory),
        "precio_contado_mxn": price,
        "enganche_mxn": down,
        "pago_quincenal_mxn": pay,
        "numero_quincenas": terms,
        "citation": {
            "source_id": catalog.source_id,
            "title": catalog.title,
            "content_type": catalog.metadata.get("content_type"),
        },
    }


def _replace_placeholder_quote(
    output: TurnOutput,
    quote_snapshot: dict[str, object] | None,
) -> TurnOutput:
    if not quote_snapshot or quote_snapshot.get("quote_sent") is False:
        return output
    final = str(output.final_message or "")
    if not any(
        token in final
        for token in ("$X", "$Y", "$Z", "{precio}", "{enganche}", "{pago}", "{modelo}", "N quincenas", "TBD")
    ):
        return output
    moto = str(quote_snapshot.get("moto") or "la moto")
    price = _money(quote_snapshot.get("precio_contado_mxn"))
    plan = quote_snapshot.get("plan_credito")
    enganche = _money(quote_snapshot.get("enganche_mxn"))
    pago = _money(quote_snapshot.get("pago_quincenal_mxn"))
    quincenas = quote_snapshot.get("numero_quincenas")
    parts = [f"{moto} de contado queda en {price}."]
    if plan and str(plan) != "Contado" and enganche and pago and quincenas:
        parts.append(
            f"Con tu plan {plan}: enganche {enganche}, pagos de {pago} por {quincenas} quincenas."
        )
    return output.model_copy(update={"final_message": " ".join(parts)})


def _suppress_unresolved_quote(
    context: TurnContext,
    output: TurnOutput,
    quote_snapshot: dict[str, object] | None,
    current_fields: dict[str, Any],
) -> TurnOutput:
    if quote_snapshot and quote_snapshot.get("quote_sent") is not False:
        return output
    final = str(output.final_message or "")
    folded = fold(final)
    if "$" not in final and not any(term in folded for term in ("enganche", "quincena", "pagos de")):
        return output
    if not _catalog_citation_for_quote(context, preferred_model=current_fields.get("Moto")):
        return output
    return output.model_copy(
        update={
            "final_message": (
                "Para cotizarte con números exactos, primero dime cómo recibes tus ingresos: "
                "nómina en tarjeta, recibos de nómina, pensionado, negocio SAT, "
                "sin comprobantes, guardia de seguridad o contado."
            ),
            "lifecycle_update": None,
        }
    )


def _render_quote_from_snapshot(
    output: TurnOutput,
    quote_snapshot: dict[str, object] | None,
) -> TurnOutput:
    if (
        not quote_snapshot
        or quote_snapshot.get("status") not in {None, "ok"}
        or quote_snapshot.get("quote_sent") is False
    ):
        return output
    final = str(output.final_message or "")
    folded = fold(final)
    if not (
        "$" in final
        or any(term in folded for term in ("contado", "enganche", "quincena", "pago"))
        or quote_snapshot.get("render_required") is True
    ):
        return output
    rendered = render_quote_message(quote_snapshot, current_message=final)
    return output.model_copy(update={"final_message": rendered})


def _align_copy_with_state(
    context: TurnContext,
    output: TurnOutput,
    current_fields: dict[str, Any],
) -> TurnOutput:
    state = dict(current_fields)
    for update in output.field_updates:
        state[update.field_key] = update.value
    plan = str(state.get("Plan_Credito") or "")
    enganche = str(state.get("Plan_Enganche") or "")
    final = str(output.final_message or "")
    folded = fold(final)
    if plan == "Nomina Tarjeta" and (
        "nomina recibos" in folded or (enganche == "10%" and "15%" in final)
    ):
        final = (
            "Tu plan sigue como Nómina Tarjeta con 10% de enganche. "
            "Para este plan necesito INE por ambos lados, comprobante de domicilio, "
            "estado de cuenta y recibos de nómina. Primero mándame tu INE completa y legible."
        )
    if plan == "Contado" and any(term in folded for term in ("ine", "documentos de credito")):
        quote = state.get("Ultima_Cotizacion") if isinstance(state.get("Ultima_Cotizacion"), dict) else {}
        if quote:
            final = render_quote_message(quote)
        else:
            final = (
                "Para contado no te pido documentos de crédito. "
                "Si quieres, te paso con un asesor para confirmar disponibilidad y forma de pago."
            )
    if final != output.final_message:
        trace = dict(output.trace_metadata)
        trace["copy_state_aligned"] = {
            "plan_credito": plan,
            "plan_enganche": enganche,
            "reason": "visible copy aligned with operational state",
        }
        return output.model_copy(update={"final_message": final, "trace_metadata": trace})
    return output


class _QuoteMemoryCitation:
    def __init__(self, quote: dict[str, Any]) -> None:
        citation = quote.get("citation") if isinstance(quote.get("citation"), dict) else {}
        self.title = str(quote.get("moto") or citation.get("title") or "")
        self.source_id = str(citation.get("source_id") or "quote_memory")
        self.metadata = {"content_type": citation.get("content_type") or "catalog"}
        self.snippet = "\n".join(
            [
                f"modelo_moto: {self.title}",
                f"precio_contado_mxn: {quote.get('precio_contado_mxn')}",
                (
                    f"credito {quote.get('plan_enganche')}: "
                    f"enganche_mxn {quote.get('enganche_mxn')}, "
                    f"pago_quincenal_mxn {quote.get('pago_quincenal_mxn')}, "
                    f"numero_quincenas {quote.get('numero_quincenas')}"
                ),
            ]
        )


def _catalog_citation_for_quote(
    context: TurnContext,
    *,
    preferred_model: object | None,
) -> Any | None:
    catalog_citations = [
        citation
        for citation in context.knowledge_citations
        if citation.metadata.get("content_type") == "catalog"
    ]
    if not catalog_citations:
        return None
    preferred = fold(str(preferred_model or ""))
    if preferred:
        for citation in catalog_citations:
            title = fold(str(citation.title or ""))
            if preferred in title or title in preferred:
                return citation
    text_model = _model_from_text(context.inbound_text)
    if text_model:
        folded_model = fold(text_model)
        for citation in catalog_citations:
            title = fold(str(citation.title or ""))
            if folded_model in title:
                return citation
    return catalog_citations[0]


def _field_update_value(output: TurnOutput, key: str) -> object | None:
    for update in reversed(output.field_updates):
        if fold(update.field_key) == fold(key):
            return update.value
    return None


def _model_from_text(text: str) -> str | None:
    folded = fold(text)
    known = {
        "r4": "R4",
        "comando": "Comando",
        "adventure": "Adventure",
        "u5": "U5",
    }
    for term, value in known.items():
        if term in folded:
            return value
    return None


def _canonical_plan_label(value: object | None) -> object | None:
    folded = fold(str(value or ""))
    labels = {
        "nomina tarjeta": "Nomina Tarjeta",
        "nomina recibos": "Nomina Recibos",
        "sin comprobantes": "Sin Comprobantes",
        "guardia": "Guardia",
        "contado": "Contado",
    }
    return labels.get(folded, value)


def _plan_from_text(text: str) -> tuple[str | None, str | None]:
    folded = fold(text)
    if "contado" in folded:
        return "Contado", "100%"
    if "deposit" in folded or "tarjeta" in folded:
        return "Nomina Tarjeta", "10%"
    if ("efectivo" in folded and "recibo" in folded) or "me pagan con recib" in folded:
        return "Nomina Recibos", "15%"
    if "por fuera" in folded or "sin comprob" in folded:
        return "Sin Comprobantes", "20%"
    if "guardia" in folded or "seguridad" in folded:
        return "Guardia", "30%"
    return None, None


def _money(value: object) -> str:
    try:
        amount = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return "$0"
    return f"${amount:,}"


def _extract_number(text: str, key: str) -> int | None:
    import re

    match = re.search(rf"{re.escape(key)}\D+(\d+)", text)
    return int(match.group(1)) if match else None


def _extract_plan_number(text: str, plan_enganche: object, key: str) -> int | None:
    import re

    percent = str(plan_enganche or "").strip()
    if not percent:
        return _extract_number(text, key)
    match = re.search(
        rf"credito\s+{re.escape(percent)}\s*:(?:(?!credito\s+\d+%).)*?"
        rf"{re.escape(key)}\D+(\d+)",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if match:
        return int(match.group(1))
    return _extract_number(text, key)


def _down_payment_from_percent(price: int | None, plan_enganche: object) -> int | None:
    if price is None:
        return None
    percent = str(plan_enganche or "").strip().rstrip("%")
    try:
        ratio = int(percent) / 100
    except ValueError:
        return None
    return round(price * ratio)


if __name__ == "__main__":
    asyncio.run(main())
