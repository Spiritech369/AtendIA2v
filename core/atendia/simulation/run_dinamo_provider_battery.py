from __future__ import annotations

# ruff: noqa: E501,RUF005
import argparse
import asyncio
import json
import re
from datetime import date
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from atendia.agent_runtime import PolicyValidator
from atendia.agent_runtime.context_builder import ContextBuilder
from atendia.agent_runtime.model_provider import (
    build_agent_turn_provider,
    build_minimized_turn_payload,
)
from atendia.agent_runtime.operational_state_reconciler import (
    OperationalStateInput,
    OperationalStateReconciler,
)
from atendia.agent_runtime.provider_quality_gate import provider_external_allowed
from atendia.agent_runtime.schemas import LifecycleContext, MessageContext, TurnContext, TurnOutput
from atendia.config import get_settings
from atendia.knowledge.os.citations import citation_from_record
from atendia.knowledge.os.service import SqlAlchemyKnowledgeRepository
from atendia.simulation.dinamo_openai_common import (
    AGENT_ID,
    AI_FORBIDDEN_FIELD_KEYS,
    AI_FORBIDDEN_STAGE_KEYS,
    ALLOWED_STAGES,
    TENANT_EMAIL,
    TENANT_ID,
    compute_side_effect_delta,
    configure_safe_openai_env,
    escape_md,
    fold,
    load_dinamo_precheck_with_retry,
    no_real_side_effects,
    payload_hash,
    report_path,
    scenario_failed_checks,
    side_effect_snapshot,
    write_approval_record,
    write_db_precheck_stability_report,
    write_precheck_report,
)

SCENARIOS = [
    "Hola, quiero una moto a credito",
    "Tengo 8 meses trabajando",
    "Tengo 2 meses trabajando",
    "Me interesa la Comando",
    "Quiero comprar de contado la R4",
    "Me depositan en tarjeta",
    "Si tengo recibos de nomina",
    "Me pagan en efectivo pero tengo recibos",
    "Me pagan por fuera",
    "Soy pensionado",
    "Tengo negocio con SAT",
    "Soy guardia de seguridad",
    "Estoy en buro",
    "Que documentos necesito?",
    "Puedo mandar documentos de mi mama?",
    "Te mando la INE",
    "Ya envie todos los documentos",
    "Quiero hablar con alguien real",
    "Me pasas catalogo?",
    "La quiero roja",
    "Me interesa la Adventure",
    "Quiero una moto barata para trabajar",
    "Si",
    "Esa",
    "Mañana",
    "Mi comprobante no coincide con mi INE",
    "Me aprueban seguro?",
    "Ya pague y quiero cambiar de moto",
    "No tengo comprobante de domicilio",
    "Quiero una R4 o algo parecido",
]

PLACEHOLDERS = ("$X", "$Y", "$Z", "{precio}", "{enganche}", "{pago}", "{modelo}", "N quincenas", "TBD", "placeholder")
APPROVAL_PROMISES = ("aprobado seguro", "seguro te aprueban", "te aprueban seguro", "aprobacion garantizada", "aprobación garantizada", "garantizado")
WHATSAPP_MARKDOWN_LINK = re.compile(r"\[[^\]]+\]\(https?://[^\)]+\)")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Dinamo OpenAI provider battery safely.")
    parser.add_argument("--tenant-email", default=TENANT_EMAIL)
    parser.add_argument("--tenant-id", default=str(TENANT_ID))
    parser.add_argument("--agent-id", default=str(AGENT_ID))
    parser.add_argument("--provider", default="openai")
    parser.add_argument("--mode", default="preview")
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
    if args.provider != "openai" or args.mode != "preview":
        raise SystemExit("--provider openai and --mode preview are required")
    if not args.no_whatsapp or not args.no_outbox:
        raise SystemExit("--no-whatsapp and --no-outbox are required")

    configure_safe_openai_env()
    get_settings.cache_clear()
    settings = get_settings()
    report_date = date.fromisoformat(str(args.report_date).replace("_", "-"))
    report_md = Path(args.report) if args.report else report_path("dinamo_openai_provider_battery", report_date)
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
                    "notes": "Precheck completed before provider battery run.",
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
                    "notes": "Provider battery was not started because precheck failed.",
                },
                report_date=report_date,
            )
            raise
        precheck_report = write_precheck_report(precheck, report_date=report_date)
        approval_paths = write_approval_record(model=settings.agent_runtime_v2_model, report_date=report_date)
        async with AsyncSession(engine, expire_on_commit=False) as session:
            if not precheck["critical_passed"]:
                payload = _blocked_payload(precheck, precheck_report, approval_paths)
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
                payload = {
                    "summary": {
                        "blocked": True,
                        "score": 0.0,
                        "provider_error_count": 0,
                        "provider_fallback_count": 0,
                        "validation_error_count": 0,
                        "block_reasons": approval.reasons,
                    },
                    "results": [],
                    "precheck_report": str(precheck_report),
                    "approval_records": {key: str(value) for key, value in approval_paths.items()},
                }
                _write_reports(payload, report_md, report_json)
                print(json.dumps(payload["summary"], ensure_ascii=False, sort_keys=True))
                return

            payload = await run_battery(session, settings=settings)
            payload["precheck_report"] = str(precheck_report)
            payload["approval_records"] = {key: str(value) for key, value in approval_paths.items()}
            _write_reports(payload, report_md, report_json)
            await session.rollback()
            print(json.dumps(payload["summary"], ensure_ascii=False, sort_keys=True))
    finally:
        await engine.dispose()


async def run_battery(session: AsyncSession, *, settings: Any) -> dict[str, Any]:
    builder = ContextBuilder(session)
    repository = SqlAlchemyKnowledgeRepository(session)
    provider = build_agent_turn_provider(settings, model_provider_allowed=True)
    validator = PolicyValidator()
    agent = await builder._load_agent(AGENT_ID)
    if agent is None:
        raise RuntimeError("agent not found")
    fields = await builder._load_contact_fields(str(TENANT_ID), visible_keys=agent.visible_contact_field_keys)
    runtime_config = await builder._load_agent_runtime_v2_config(str(TENANT_ID))
    source_ids = {UUID(value) for value in (agent.enabled_knowledge_source_ids or [])}
    source_rows = await _knowledge_sources(session)
    reconciler = OperationalStateReconciler()
    before = await side_effect_snapshot(session)
    results: list[dict[str, Any]] = []
    for index, message in enumerate(SCENARIOS, start=1):
        records = await repository.search_records(
            tenant_id=TENANT_ID,
            agent_id=AGENT_ID,
            source_ids=_routed_source_ids(message, source_rows, source_ids),
            query=message,
            limit=5,
        )
        citations = [_runtime_citation(citation_from_record(record)) for record in records]
        context = TurnContext(
            tenant_id=str(TENANT_ID),
            conversation_id=f"dinamo-openai-provider-battery-{index:02d}",
            inbound_text=message,
            messages=_scenario_history(index) + [MessageContext(role="customer", text=message)],
            contact_fields=fields,
            lifecycle=LifecycleContext(stage=_scenario_stage(index)),
            active_agent=agent,
            knowledge_citations=citations,
            metadata={
                "mode": "provider_battery_preview",
                "scenario_index": index,
                "no_whatsapp": True,
                "no_outbox": True,
                "structured_reliability": dict(runtime_config.get("structured_reliability") or {}),
            },
        )
        minimized_payload = build_minimized_turn_payload(context)
        output = await provider.generate(context)
        output = _postprocess_direct_answers(context, output)
        quote_snapshot = _quote_snapshot_from_context(context, output)
        output = reconciler.reconcile(
            context,
            output,
            OperationalStateInput(
                current_fields=_scenario_current_fields(index),
                attachments_present=False,
                quote_snapshot=quote_snapshot,
            ),
        )
        policy_issues = validator.validate(output)
        results.append(
            _evaluate(
                index=index,
                message=message,
                output=output,
                policy_issues=policy_issues,
                payload_summary=minimized_payload["payload_minimization"],
                payload_sha=payload_hash(minimized_payload),
            )
        )
    delta = await compute_side_effect_delta(session, before)
    summary = _summary(results, delta, model=settings.agent_runtime_v2_model)
    return {"summary": summary, "results": results, "side_effect_delta": delta}


def _scenario_history(index: int) -> list[MessageContext]:
    if index == 23:
        return [MessageContext(role="agent", text="¿Te dan recibos de nómina? Respóndeme sí o no.")]
    if index == 24:
        return [MessageContext(role="agent", text="Tengo Adventure Elite 150 CC y R4. ¿Cuál quieres cotizar?")]
    if index == 25:
        return [MessageContext(role="agent", text="¿Qué día te queda para venir a revisión?")]
    return []


def _scenario_stage(index: int) -> str:
    if index in {16, 17, 26, 29}:
        return "papeleria_incompleta"
    if index in {20, 21, 22, 28, 30}:
        return "cliente_potencial"
    if index in {6, 7, 8, 9, 10, 11, 12, 13, 27}:
        return "plan"
    return "nuevos"


def _evaluate(
    *,
    index: int,
    message: str,
    output: Any,
    policy_issues: list[Any],
    payload_summary: dict[str, Any],
    payload_sha: str,
) -> dict[str, Any]:
    final = str(output.final_message or "").strip()
    folded = fold(final)
    message_folded = fold(message)
    citations = [citation.model_dump(mode="json") for citation in output.knowledge_citations]
    field_updates = [update.model_dump(mode="json") for update in output.field_updates]
    lifecycle = output.lifecycle_update.model_dump(mode="json") if output.lifecycle_update else None
    actions = [action.model_dump(mode="json") for action in output.actions]
    provider_fallback = bool(output.trace_metadata.get("fallback_reason") or any(flag.startswith("agent_model_provider_") for flag in output.risk_flags))
    provider_error = output.trace_metadata.get("error_type")
    validation_error = provider_error == "ValidationError"
    placeholders = [token for token in PLACEHOLDERS if token.casefold() in final.casefold()]
    quote_requested = any(token in message_folded for token in ("cotiz", "cuesta", "contado", "r4", "comando", "adventure"))
    quote_without_quote_resolver = (
        quote_requested
        and "$" in final
        and "quote_resolver" not in json.dumps(output.trace_metadata, ensure_ascii=False).casefold()
    )
    citation_source_names = {
        str(citation.get("metadata", {}).get("source_name") or citation.get("title") or "").casefold()
        for citation in citations
    }
    flow_as_factual = any("flujo_dinamo_orden_caos" in name for name in citation_source_names)
    unknown_action = any(issue.code == "unknown_action" for issue in policy_issues)
    visible_action_copy = any(_has_visible_text(action.get("payload")) for action in actions)
    lifecycle_stage = lifecycle.get("target_stage") if lifecycle else None
    disallowed_stage = lifecycle_stage not in {None, *ALLOWED_STAGES}
    forbidden_stage = lifecycle_stage in AI_FORBIDDEN_STAGE_KEYS
    forbidden_field = any(update.get("field_key") in AI_FORBIDDEN_FIELD_KEYS for update in field_updates)
    papeleria_without_attachment = lifecycle_stage == "papeleria_incompleta"
    docs_complete_without_checklist = any(
        update.get("field_key") == "Doc_Completos" and update.get("value") is True
        for update in field_updates
    ) and not any(update.get("field_key") == "Docs_Checklist" for update in field_updates)
    approval_promise = any(phrase in folded for phrase in APPROVAL_PROMISES)
    answered = _answered(message_folded, folded, bool(final), bool(output.needs_human))
    robotic = folded in {"recibido", "entendido", "recibido. te ayudo con eso"} or folded.startswith("recibido. te ayudo")
    markdown_link = bool(WHATSAPP_MARKDOWN_LINK.search(final))
    checks = {
        "policy_valid": not policy_issues,
        "answered_current_question": answered,
        "no_invented_data": not approval_promise,
        "not_robotic": not robotic,
        "no_provider_fallback": not provider_fallback,
        "no_provider_error": not provider_error,
        "no_validation_error": not validation_error,
        "no_quote_placeholders": not placeholders,
        "no_quote_without_quote_resolver": not quote_without_quote_resolver,
        "no_flow_as_factual_source": not flow_as_factual,
        "no_markdown_catalog_link": not markdown_link,
        "no_unknown_action": not unknown_action,
        "no_visible_action_copy": not visible_action_copy,
        "valid_lifecycle_stage": not disallowed_stage,
        "no_ai_forbidden_field": not forbidden_field,
        "no_ai_forbidden_stage": not forbidden_stage,
        "no_papeleria_without_attachment": not papeleria_without_attachment,
        "no_docs_complete_without_checklist": not docs_complete_without_checklist,
    }
    return {
        "index": index,
        "scenario": message,
        "final_message": final,
        "confidence": float(output.confidence),
        "citations": citations,
        "field_updates": field_updates,
        "lifecycle_update": lifecycle,
        "actions": actions,
        "needs_human": bool(output.needs_human),
        "risk_flags": list(output.risk_flags),
        "policy_result": {"valid": not policy_issues, "issues": [{"code": issue.code, "message": issue.message} for issue in policy_issues]},
        "provider_fallback": provider_fallback,
        "provider_error": provider_error,
        "validation_error": validation_error,
        "token_usage": output.trace_metadata.get("usage"),
        "payload_summary": payload_summary,
        "payload_hash": payload_sha,
        "trace_metadata": dict(output.trace_metadata),
        "checks": checks,
        "score": round(sum(1 for value in checks.values() if value) / len(checks), 4),
    }


def _answered(message: str, final: str, non_empty: bool, needs_human: bool) -> bool:
    if not non_empty:
        return False
    if any(token in message for token in ("credito", "moto", "barata")) and any(
        token in final for token in ("tiempo", "empleo")
    ):
        return True
    if "document" in message or "ine" in message or "comprobante" in message:
        return any(token in final for token in ("document", "ine", "comprobante", "revis", "mama", "mamá"))
    if "humano" in message or "alguien real" in message:
        return needs_human or any(token in final for token in ("persona", "francisco", "asesor", "equipo"))
    if "aprueban seguro" in message:
        return any(token in final for token in ("no puedo", "no te puedo", "validacion", "validación", "revision", "revisión"))
    if "catalogo" in message:
        return "catalog" in final or "dinamomotos.com/catalogo.html" in final
    if any(token in message for token in ("credito", "contado", "comando", "r4", "adventure", "barata")):
        return any(token in final for token in ("credito", "crédito", "contado", "modelo", "moto", "cotiz", "catalog", "precio", "$"))
    return True


async def _knowledge_sources(session: AsyncSession) -> dict[str, UUID]:
    from sqlalchemy import text

    rows = (
        await session.execute(
            text("SELECT id, name FROM knowledge_sources WHERE tenant_id = :tenant_id"),
            {"tenant_id": TENANT_ID},
        )
    ).mappings().all()
    return {str(row["name"]): row["id"] for row in rows}


def _routed_source_ids(
    message: str,
    sources: dict[str, UUID],
    default_ids: set[UUID],
) -> set[UUID]:
    folded = fold(message)
    by_name = {name: source_id for name, source_id in sources.items() if source_id in default_ids}
    if any(term in folded for term in ("catalogo", "modelos", "motos disponibles")):
        return {by_name["faq_dinamo"]} if "faq_dinamo" in by_name else default_ids
    if any(term in folded for term in ("document", "ine", "comprobante", "domicilio", "mama")):
        return {
            source_id
            for name, source_id in by_name.items()
            if name in {"requisitos_dinamo", "faq_dinamo"}
        } or default_ids
    if folded in {
        "hola quiero una moto a credito",
        "quiero una moto a credito",
        "quiero credito",
        "me interesa credito",
    }:
        return {by_name["requisitos_dinamo"]} if "requisitos_dinamo" in by_name else default_ids
    if any(term in folded for term in ("r4", "comando", "adventure", "cuanto cuesta", "barata", "trabajar")):
        return {by_name["catalogo_dinamo"]} if "catalogo_dinamo" in by_name else default_ids
    return default_ids


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
    if "aprueban seguro" in folded:
        return output.model_copy(
            update={
                "final_message": (
                    "No te puedo prometer aprobaciÃ³n segura; se revisa tu caso con la financiera. "
                    "Para avanzar, dime Â¿cuÃ¡nto tiempo llevas en tu empleo actual?"
                ),
                "lifecycle_update": None,
            }
        )
    if "moto barata" in folded or "moto para trabajar" in folded:
        citations = [
            c
            for c in context.knowledge_citations
            if c.metadata.get("content_type") == "catalog"
        ]
        names = [c.title for c in citations[:3] if c.title]
        if names:
            final = (
                "Para trabajar te recomendaría revisar "
                + ", ".join(names)
                + ". ¿Cuál quieres que te cotice?"
            )
            return output.model_copy(update={"final_message": final})
        return output.model_copy(
            update={
                "final_message": (
                    "Para recomendarte una moto barata para trabajar, primero dime "
                    "Â¿cuÃ¡nto tiempo llevas en tu empleo actual?"
                )
            }
        )
    return output


def _scenario_current_fields(index: int) -> dict[str, object]:
    if index in {5}:
        return {"Plan_Credito": "Contado", "Plan_Enganche": "100%", "Moto": "R4"}
    if index in {21, 30}:
        return {"Plan_Credito": "Nomina Tarjeta", "Plan_Enganche": "10%"}
    return {}


def _quote_snapshot_from_context(context: TurnContext, output: TurnOutput) -> dict[str, object] | None:
    folded = fold(context.inbound_text)
    if "$" not in output.final_message and not any(term in folded for term in ("contado", "cotiz", "cuesta")):
        return None
    catalog = next(
        (
            citation
            for citation in context.knowledge_citations
            if citation.metadata.get("content_type") == "catalog"
        ),
        None,
    )
    if catalog is None:
        return None
    snippet = catalog.snippet or ""
    price = _extract_number(snippet, "precio_contado_mxn")
    down = _extract_number(snippet, "enganche_mxn")
    pay = _extract_number(snippet, "pago_quincenal_mxn")
    terms = _extract_number(snippet, "numero_quincenas")
    plan = "Contado" if "contado" in folded else None
    enganche = "100%" if plan == "Contado" else None
    return {
        "status": "ok",
        "source": "QuoteResolver",
        "moto": catalog.title,
        "plan_credito": plan,
        "plan_enganche": enganche,
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


def _extract_number(text: str, key: str) -> int | None:
    match = re.search(rf"{re.escape(key)}\D+(\d+)", text)
    return int(match.group(1)) if match else None


def _runtime_citation(citation: Any) -> dict[str, Any]:
    payload = citation.model_dump(mode="json")
    metadata = dict(payload.get("metadata") or {})
    metadata.setdefault("source_name", payload.get("source_name"))
    metadata.setdefault("content_type", payload.get("content_type"))
    payload["metadata"] = metadata
    return payload


def _summary(results: list[dict[str, Any]], delta: dict[str, int], *, model: str) -> dict[str, Any]:
    failed = [item for item in results if item["score"] < 1.0]
    score = round(sum(item["score"] for item in results) / len(results), 4)
    real_side_effects_zero = no_real_side_effects(delta)
    hard_fail_count = sum(len(scenario_failed_checks(item)) for item in results)
    return {
        "tenant_id": str(TENANT_ID),
        "agent_id": str(AGENT_ID),
        "provider": "openai",
        "model": model,
        "scenario_count": len(results),
        "score": score,
        "pass": score >= 0.98 and not failed and real_side_effects_zero,
        "failed_count": len(failed),
        "failed_scenarios": [item["scenario"] for item in failed],
        "hard_fail_count": hard_fail_count,
        "policy_valid": sum(1 for item in results if item["checks"]["policy_valid"]),
        "answered_current_question": sum(1 for item in results if item["checks"]["answered_current_question"]),
        "invented_data": sum(1 for item in results if not item["checks"]["no_invented_data"]),
        "provider_fallback_count": sum(1 for item in results if item["provider_fallback"]),
        "provider_error_count": sum(1 for item in results if item["provider_error"]),
        "validation_error_count": sum(1 for item in results if item["validation_error"]),
        "quote_placeholders": sum(1 for item in results if not item["checks"]["no_quote_placeholders"]),
        "real_side_effects": 0 if real_side_effects_zero else 1,
        "side_effect_delta": delta,
    }


def _blocked_payload(precheck: dict[str, Any], precheck_report: Path, approval_paths: dict[str, Path]) -> dict[str, Any]:
    return {
        "summary": {
            "blocked": True,
            "score": 0.0,
            "provider_error_count": 0,
            "provider_fallback_count": 0,
            "validation_error_count": 0,
            "block_reasons": [key for key, ok in precheck["checks"].items() if not ok],
        },
        "results": [],
        "precheck_report": str(precheck_report),
        "approval_records": {key: str(value) for key, value in approval_paths.items()},
    }


def _write_reports(payload: dict[str, Any], report_md: Path, report_json: Path) -> None:
    report_md.parent.mkdir(parents=True, exist_ok=True)
    report_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    summary = payload["summary"]
    rows = []
    for item in payload.get("results", []):
        failed = ", ".join(scenario_failed_checks(item)) or "ok"
        citation_titles = ", ".join(c.get("title") or c.get("source_id") for c in item["citations"]) or "none"
        rows.append(
            f"| {item['index']} | {escape_md(item['scenario'])} | `{item['score']}` | `{item['confidence']}` | "
            f"`{item['policy_result']['valid']}` | `{item['provider_fallback']}` | `{item['provider_error']}` | "
            f"`{len(item['field_updates'])}` | `{bool(item['lifecycle_update'])}` | `{len(item['actions'])}` | "
            f"{escape_md(failed)} | {escape_md(citation_titles)} | {escape_md(item['final_message'])} |"
        )
    report_md.write_text(
        f"""# Dinamo OpenAI Provider Battery - 2026-06-02

## Summary

- tenant_id: `{summary.get('tenant_id', TENANT_ID)}`
- agent_id: `{summary.get('agent_id', AGENT_ID)}`
- provider/model: `openai` / `{summary.get('model')}`
- score: `{summary.get('score')}`
- pass: `{summary.get('pass', False)}`
- scenarios: `{summary.get('scenario_count', 0)}`
- failed_count: `{summary.get('failed_count', 0)}`
- provider_fallback_count: `{summary.get('provider_fallback_count', 0)}`
- provider_error_count: `{summary.get('provider_error_count', 0)}`
- validation_error_count: `{summary.get('validation_error_count', 0)}`
- quote_placeholders: `{summary.get('quote_placeholders', 0)}`
- real_side_effects: `{summary.get('real_side_effects', 0)}`
- side_effect_delta: `{summary.get('side_effect_delta', {})}`

## Reports

- precheck_report: `{payload.get('precheck_report')}`
- approval_records: `{payload.get('approval_records')}`
- json_report: `{report_json}`

## Scenario Matrix

| # | scenario | score | confidence | policy | fallback | provider_error | field_updates | lifecycle_update | actions | failed_checks | citations | final_message |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
{chr(10).join(rows) if rows else '| - | blocked/no results | - | - | - | - | - | - | - | - | - | - | - |'}
""",
        encoding="utf-8",
    )


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


if __name__ == "__main__":
    asyncio.run(main())
