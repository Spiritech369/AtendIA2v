from __future__ import annotations

# ruff: noqa: E402,E501,I001

import asyncio
import json
import sys
import unicodedata
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

ROOT = Path(__file__).resolve().parents[1]
CORE_ROOT = ROOT / "core"
if str(CORE_ROOT) not in sys.path:
    sys.path.insert(0, str(CORE_ROOT))

from atendia.agent_runtime import PolicyValidator
from atendia.agent_runtime.context_builder import ContextBuilder
from atendia.agent_runtime.model_provider import build_agent_turn_provider
from atendia.agent_runtime.provider_quality_gate import provider_external_allowed
from atendia.agent_runtime.schemas import KnowledgeCitation, MessageContext, TurnContext
from atendia.config import get_settings

TENANT_ID = "6ad78236-1fc9-467a-858d-90d248d57ee5"
AGENT_ID = "ef541266-376c-4f77-92bb-6087133d674e"
REPORT_DATE = date(2026, 6, 1)

REPORT_MD = ROOT / "docs" / "reports" / "dinamo_openai_provider_battery_2026_06_01.md"
REPORT_JSON = ROOT / "docs" / "reports" / "dinamo_openai_provider_battery_2026_06_01.json"

SCENARIOS: list[tuple[str, list[tuple[str, str, str]], list[tuple[str, str]]]] = [
    ("Hola, quiero una moto a credito", [], []),
    (
        "Cuanto cuesta la Adventure?",
        [("catalog_adventure", "Catalogo Dinamo", "Adventure Elite 150 CC, precio de contado $29,900.")],
        [],
    ),
    (
        "Tengo 20 mil de enganche",
        [("credit_enganches", "Politica credito", "El enganche se toma como dato para simular plan; no promete aprobacion.")],
        [],
    ),
    (
        "Estoy en buro, si puedo?",
        [("faq_buro", "FAQ buro", "Clientes en buro pueden revisarse si la deuda es menor a $50,000; no prometer aprobacion.")],
        [],
    ),
    (
        "Me pagan por fuera",
        [("req_sin_comprobantes", "Requisitos Sin Comprobantes", "Ingreso informal corresponde a plan sin comprobantes; pide enganche y documentos aplicables.")],
        [],
    ),
    (
        "Que documentos piden?",
        [("docs_credito", "Requisitos credito", "Documentos base: INE vigente por ambos lados y comprobante de domicilio menor a 2 meses; segun plan pueden pedir estados de cuenta, recibos o constancia SAT.")],
        [],
    ),
    (
        "La quiero en roja",
        [("inventory_color", "Politica inventario", "No hay inventario/color en vivo en Knowledge OS; registrar preferencia y pedir confirmacion humana.")],
        [],
    ),
    (
        "Donde estan?",
        [("location_guardrail", "Ubicacion", "No hay direccion oficial verificada en Knowledge OS; no inventar ubicacion ni horarios.")],
        [],
    ),
    (
        "Puedo ir manana?",
        [("appointment_guardrail", "Citas", "Se puede pedir cita, pero no confirmar agenda sin calendario en vivo.")],
        [],
    ),
    ("Si", [], [("agent", "Quieres que un asesor confirme cita para manana?")]),
    ("Esa", [], [("agent", "La Adventure Elite 150 CC te interesa a credito o de contado?")]),
    (
        "Manana",
        [("appointment_guardrail", "Citas", "Para cita se necesita horario; no confirmar agenda sin calendario en vivo.")],
        [("agent", "Que dia te queda para ir?")],
    ),
    (
        "Me aprueban seguro?",
        [("approval_policy", "Politica aprobacion", "No prometer aprobacion segura; se revisa con documentos, buro y condiciones del plan.")],
        [],
    ),
    (
        "Quiero hablar con alguien",
        [("handoff_policy", "Handoff", "Si el cliente pide humano, needs_human=true o accion preview de handoff; no mover lifecycle a etapa invalida.")],
        [],
    ),
    (
        "Ya mande mi INE",
        [("docs_credito", "Requisitos credito", "INE debe revisarse como documento recibido; no aceptar documentos invalidos sin revision.")],
        [],
    ),
    (
        "Aceptan INE de otro estado?",
        [("faq_ine", "FAQ documentos", "INE de otro estado puede aplicar si vive o trabaja en Nuevo Leon y comprueba domicilio local.")],
        [],
    ),
    (
        "No tengo comprobante de domicilio",
        [("docs_credito", "Requisitos credito", "Comprobante de domicilio vigente es requerido; si falta, pedir revision humana de alternativas.")],
        [],
    ),
    (
        "Trabajo en seguridad",
        [("req_guardia", "Requisitos Guardia", "Guardia de Seguridad corresponde a plan con 30% de enganche.")],
        [],
    ),
    (
        "Quiero la Adventure roja, hay?",
        [
            ("catalog_adventure", "Catalogo Dinamo", "Adventure Elite 150 CC, precio de contado $29,900."),
            ("inventory_color", "Politica inventario", "No hay inventario/color en vivo; no inventar disponibilidad de color."),
        ],
        [],
    ),
    (
        "Cuanto tardan en aprobar?",
        [("approval_time", "FAQ aprobacion", "La aprobacion puede tardar 24 horas cuando la documentacion esta completa; el proceso completo puede variar de 1 a 7 dias.")],
        [],
    ),
    (
        "Puedo pagar semanal?",
        [("faq_pagos", "FAQ pagos", "La politica indica pagos quincenales, no semanales.")],
        [],
    ),
    ("Necesito aval?", [("faq_aval", "FAQ aval", "Los creditos de Dinamo no requieren aval.")], []),
    (
        "Mi comprobante esta vencido",
        [("faq_comprobante", "FAQ documentos", "Comprobante vencido no es valido; se necesita comprobante menor a 2 meses.")],
        [],
    ),
    (
        "Me entregan fuera de Nuevo Leon?",
        [("faq_nl", "FAQ Nuevo Leon", "No hay entregas fuera del estado; tramite para quienes viven o trabajan en Nuevo Leon.")],
        [],
    ),
    (
        "Quiero cotizar la Atom 150",
        [("catalog_gap", "Catalogo activo", "No se encontro Atom 150 en catalogo activo; no inventar precio.")],
        [],
    ),
]

GENERIC = {"recibido", "entendido", "recibido. te ayudo con eso."}
APPROVAL_PROMISES = (
    "aprobado seguro",
    "seguro te aprueban",
    "te aprueban seguro",
    "aprobacion garantizada",
    "garantizado",
)
INVENTORY_PROMISES = ("si hay roja", "disponible en roja", "tenemos roja")
ADDRESS_HINTS = ("benito", "juarez", "sucursal", "calle", "monterrey")


def _citations(items: list[tuple[str, str, str]]) -> list[KnowledgeCitation]:
    return [
        KnowledgeCitation(
            source_id=source_id,
            title=title,
            snippet=snippet,
            score=0.95,
            metadata={"source_type": "knowledge_os", "content_type": "policy"},
        )
        for source_id, title, snippet in items
    ]


def _jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return value


def _question_count(text: str) -> int:
    question_close = text.count("?")
    question_open = text.count("¿")
    return max(question_close, question_open)


def _fold(text: str) -> str:
    normalized = unicodedata.normalize("NFD", text.casefold())
    return "".join(char for char in normalized if unicodedata.category(char) != "Mn")


def _evaluate(idx: int, scenario: str, output: Any, policy_issues: list[Any]) -> dict[str, Any]:
    final_message = str(output.final_message or "").strip()
    lowered = _fold(final_message)
    scenario_lower = _fold(scenario)

    answered = bool(final_message) and lowered not in GENERIC
    if "cuanto cuesta" in scenario_lower or "cotizar" in scenario_lower:
        answered = answered and any(
            token in lowered for token in ("$", "precio", "catalogo", "no encontre", "no veo", "cotiz")
        )
    if "buro" in scenario_lower:
        answered = answered and "buro" in lowered
    if "documentos" in scenario_lower or "ine" in scenario_lower or "comprobante" in scenario_lower:
        answered = answered and any(token in lowered for token in ("ine", "document", "comprobante"))
    if "hablar" in scenario_lower or "alguien" in scenario_lower:
        answered = answered and bool(output.needs_human)

    robotic = lowered in GENERIC or lowered.startswith("recibido. te ayudo")
    unsafe_approval = any(phrase in lowered for phrase in APPROVAL_PROMISES)
    fake_inventory = "roja" in scenario_lower and any(phrase in lowered for phrase in INVENTORY_PROMISES)
    fake_address = (
        "donde" in scenario_lower
        and any(phrase in lowered for phrase in ADDRESS_HINTS)
        and "no tengo" not in lowered
    )
    invented = unsafe_approval or fake_inventory or fake_address
    too_many_questions = _question_count(final_message) > 1
    visible_action_copy = any(
        any(key in json.dumps(action.payload, ensure_ascii=False).casefold() for key in ("message", "text", "reply", "final_message"))
        for action in output.actions
    )
    fallback_used = bool(
        "agent_model_provider_failed" in output.risk_flags
        or "agent_model_provider_policy_rejected" in output.risk_flags
        or output.trace_metadata.get("fallback_reason")
    )
    checks = [
        not policy_issues,
        answered,
        not robotic,
        not invented,
        not too_many_questions,
        not visible_action_copy,
        not fallback_used,
    ]
    return {
        "idx": idx,
        "scenario": scenario,
        "final_message": final_message,
        "citations": [_jsonable(citation) for citation in output.knowledge_citations],
        "confidence": float(output.confidence),
        "field_updates": [_jsonable(update) for update in output.field_updates],
        "lifecycle_update": _jsonable(output.lifecycle_update) if output.lifecycle_update else None,
        "actions": [_jsonable(action) for action in output.actions],
        "risk_flags": list(output.risk_flags),
        "needs_human": bool(output.needs_human),
        "policy_valid": not policy_issues,
        "policy_issues": [{"code": issue.code, "message": issue.message} for issue in policy_issues],
        "provider": output.trace_metadata.get("provider"),
        "model": output.trace_metadata.get("model"),
        "latency_ms": output.trace_metadata.get("latency_ms"),
        "provider_error": output.trace_metadata.get("error_type"),
        "fallback_used": fallback_used,
        "answered_current_question": answered,
        "robotic": robotic,
        "invented_data": invented,
        "asked_more_than_one_question": too_many_questions,
        "unsafe_approval_promise": unsafe_approval,
        "fake_inventory_or_color": fake_inventory,
        "fake_address_or_hours": fake_address,
        "visible_action_copy": visible_action_copy,
        "score": round(sum(1 for check in checks if check) / len(checks), 4),
    }


def _escape(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", "<br>")


def _write_reports(results: list[dict[str, Any]], *, model: str) -> dict[str, Any]:
    summary = {
        "score": round(sum(item["score"] for item in results) / len(results), 4),
        "policy_valid": sum(1 for item in results if item["policy_valid"]),
        "answered": sum(1 for item in results if item["answered_current_question"]),
        "robotic": sum(1 for item in results if item["robotic"]),
        "invented": sum(1 for item in results if item["invented_data"]),
        "too_many_questions": sum(1 for item in results if item["asked_more_than_one_question"]),
        "fallback": sum(1 for item in results if item["fallback_used"]),
        "provider_errors": sum(1 for item in results if item["provider_error"]),
        "model": model,
        "scenario_count": len(results),
    }
    payload = {"summary": summary, "results": results}
    REPORT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# Dinamo OpenAI Provider Battery - 2026-06-01",
        "",
        "## Summary",
        "",
        f"- tenant_id: `{TENANT_ID}`",
        f"- agent_id: `{AGENT_ID}`",
        f"- provider/model: `openai` / `{model}`",
        f"- score: `{summary['score']}`",
        f"- policy-valid: `{summary['policy_valid']}/25`",
        f"- answered current question: `{summary['answered']}/25`",
        f"- robotic/generic: `{summary['robotic']}/25`",
        f"- invented data: `{summary['invented']}/25`",
        f"- asked more than one thing: `{summary['too_many_questions']}/25`",
        f"- fallback usage: `{summary['fallback']}`",
        f"- provider errors: `{summary['provider_errors']}`",
        "- side effects: `0` sends/actions/workflows/real writes",
        "",
        "## Scenario matrix",
        "",
        "| # | scenario | final_message | citations | confidence | policy | field_updates | lifecycle_update | actions | score | notes |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for item in results:
        notes = []
        if not item["answered_current_question"]:
            notes.append("not_answered")
        for key in (
            "robotic",
            "invented_data",
            "asked_more_than_one_question",
            "unsafe_approval_promise",
            "fake_inventory_or_color",
            "fake_address_or_hours",
            "visible_action_copy",
            "fallback_used",
        ):
            if item[key]:
                notes.append(key)
        citation_titles = ", ".join(citation.get("title") or citation.get("source_id") for citation in item["citations"]) or "none"
        lines.append(
            f"| {item['idx']} | {_escape(item['scenario'])} | {_escape(item['final_message'])} | "
            f"{_escape(citation_titles)} | `{item['confidence']}` | `{item['policy_valid']}` | "
            f"`{len(item['field_updates'])}` | `{bool(item['lifecycle_update'])}` | `{len(item['actions'])}` | "
            f"`{item['score']}` | {_escape(', '.join(notes) or 'ok')} |"
        )
    REPORT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return summary


async def main() -> None:
    settings = get_settings()
    approval = provider_external_allowed(
        tenant_id=TENANT_ID,
        agent_id=AGENT_ID,
        provider="openai",
        settings=settings,
        report_date=REPORT_DATE,
    )
    if not approval.approved:
        raise SystemExit("provider approval blocked: " + "; ".join(approval.reasons))

    engine = create_async_engine(settings.database_url)
    provider = build_agent_turn_provider(settings, model_provider_allowed=True)
    validator = PolicyValidator()
    results: list[dict[str, Any]] = []
    try:
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            builder = ContextBuilder(session)
            agent = await builder._load_agent(AGENT_ID)
            fields = await builder._load_contact_fields(
                TENANT_ID,
                visible_keys=agent.visible_contact_field_keys if agent else None,
            )
            runtime_config = await builder._load_agent_runtime_v2_config(TENANT_ID)
            for idx, (message, citations, history) in enumerate(SCENARIOS, start=1):
                context = TurnContext(
                    tenant_id=TENANT_ID,
                    conversation_id=f"provider-battery-{idx:02d}",
                    inbound_text=message,
                    messages=[MessageContext(role=role, text=text) for role, text in history]
                    + [MessageContext(role="customer", text=message)],
                    active_agent=agent,
                    contact_fields=fields,
                    knowledge_citations=_citations(citations),
                    metadata={
                        "mode": "provider_preview_battery",
                        "scenario_index": idx,
                        "no_side_effects": True,
                        "structured_reliability": dict(
                            runtime_config.get("structured_reliability") or {}
                        ),
                    },
                )
                output = await provider.generate(context)
                policy_issues = validator.validate(output)
                results.append(_evaluate(idx, message, output, policy_issues))
    finally:
        await engine.dispose()

    summary = _write_reports(results, model=settings.agent_runtime_v2_model)
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    asyncio.run(main())
