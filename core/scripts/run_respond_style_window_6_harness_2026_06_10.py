"""Respond-Style Window 6 harness for the real Dinamo tenant.

This is deliberately marked simulated_inbound_shadow. It avoids the full
Baileys endpoint because that path evaluates workflow triggers before the
Respond-Style shadow hook. Instead it persists WhatsApp-shaped inbound rows
and calls the exact run_inbound_shadow hook used by Baileys step 2c.
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select, text

from atendia.db.models.conversation import Conversation, ConversationStateRow
from atendia.db.models.customer import Customer
from atendia.db.models.message import MessageRow
from atendia.db.models.product_agent import AgentDeployment, RespondStyleShadowFields
from atendia.db.session import _get_factory
from atendia.product_agents.inbound_shadow import (
    SHADOW_ROUTER_TRIGGER,
    run_inbound_shadow,
)

TENANT_ID = UUID("6ad78236-1fc9-467a-858d-90d248d57ee5")
DEPLOYMENT_ID = UUID("0a24dc41-b704-47a5-ba4b-519f9561f471")
ALLOWLIST_PHONE = "8128889241"
FROM_PHONE_E164 = "+5218128889241"
EXPECTED_MODEL = "gpt-4o"
REPORT_DATE = "2026-06-10"


@dataclass(frozen=True)
class HarnessTurn:
    turn_number: int
    text: str
    window: str = "main"
    media_type: str | None = None
    critical: bool = False


MAIN_TURNS: list[HarnessTurn] = [
    HarnessTurn(1, "hola quiero mas informacion del credito"),
    HarnessTurn(2, "te mande una imagen de una moto"),
    HarnessTurn(3, "[MEDIA:image/jpeg sin caption]", media_type="image/jpeg", critical=True),
    HarnessTurn(4, "que motos manejan?", critical=True),
    HarnessTurn(5, "tengo desde noviembre trabajando"),
    HarnessTurn(6, "perdon no noviembre, tengo 5 años", critical=True),
    HarnessTurn(7, "me pagan por nomina tarjeta", critical=True),
    HarnessTurn(8, "realmente es transferencia bancaria no nomina", critical=True),
    HarnessTurn(9, "no me dan resibos ni nada"),
    HarnessTurn(10, "entonces que plan seria?", critical=True),
    HarnessTurn(11, "me interesa la U2", critical=True),
    HarnessTurn(12, "y la metro?", critical=True),
    HarnessTurn(13, "esa cuanto queda?", critical=True),
    HarnessTurn(14, "y si estoy en buro?", critical=True),
    HarnessTurn(15, "debo como 20 mil creo", critical=True),
    HarnessTurn(16, "que ocupo mandar?", critical=True),
    HarnessTurn(17, "no quiero mandar mil papeles"),
    HarnessTurn(18, "esta caro"),
    HarnessTurn(19, "hay una mas barata?", critical=True),
    HarnessTurn(20, "pasame con alguien", critical=True),
]

ORTHOGRAPHY_TURNS: list[HarnessTurn] = [
    HarnessTurn(21, "kiero info, cuanto doy?", window="orthography"),
    HarnessTurn(22, "me pagan por NOMINA, bueno nómina o nomina en tarjeta", window="orthography"),
    HarnessTurn(23, "es tranferencia, perdon transferencia bancaria", window="orthography", critical=True),
    HarnessTurn(24, "no tengo resibos", window="orthography"),
    HarnessTurn(25, "buro o buró afecta?", window="orthography", critical=True),
    HarnessTurn(26, "cuanto queda", window="orthography", critical=True),
]

ALL_TURNS = [*MAIN_TURNS, *ORTHOGRAPHY_TURNS]


async def main() -> int:
    run_id = f"respond_style_window_6_harness_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}_{uuid4().hex[:8]}"
    factory = _get_factory()
    async with factory() as session:
        prechecks = await _prechecks(session)
        state_before = await _state_before(session)
        baselines = await _baselines(session)
        main_conversation = await _create_harness_conversation(session, run_id, "main")
        orthography_conversation = await _create_harness_conversation(
            session, run_id, "orthography"
        )
        await session.flush()

        turn_evidence: list[dict[str, Any]] = []
        for turn in ALL_TURNS:
            conversation = (
                orthography_conversation if turn.window == "orthography" else main_conversation
            )
            evidence = await _run_turn(
                session,
                run_id=run_id,
                conversation_id=conversation.id,
                turn=turn,
            )
            turn_evidence.append(evidence)
            await session.flush()

        await session.commit()

        final_state_main = await _shadow_state(session, main_conversation.id)
        final_state_orthography = await _shadow_state(session, orthography_conversation.id)
        postchecks = await _postchecks(
            session,
            baselines=baselines,
            conversation_ids=[main_conversation.id, orthography_conversation.id],
        )

    report = _render_report(
        run_id=run_id,
        prechecks=prechecks,
        state_before=state_before,
        baselines=baselines,
        postchecks=postchecks,
        main_conversation_id=str(main_conversation.id),
        orthography_conversation_id=str(orthography_conversation.id),
        final_state_main=final_state_main,
        final_state_orthography=final_state_orthography,
        turns=turn_evidence,
    )
    print(report)
    return 0


async def _prechecks(session: Any) -> dict[str, Any]:
    deployment = await session.get(AgentDeployment, DEPLOYMENT_ID)
    if deployment is None:
        raise RuntimeError(f"deployment_not_found:{DEPLOYMENT_ID}")
    metadata = dict(deployment.metadata_json or {})
    customer = await _customer(session)
    outbox_pending_retry = await _scalar(
        session,
        "SELECT COUNT(*) FROM outbound_outbox WHERE status IN ('pending','retry')",
    )
    state_rows = await _scalar(
        session,
        """
        SELECT COUNT(*)
        FROM respond_style_shadow_fields sf
        JOIN conversations c ON c.id = sf.conversation_id
        WHERE sf.tenant_id = :tenant_id
          AND c.customer_id = :customer_id
        """,
        {"tenant_id": TENANT_ID, "customer_id": customer.id},
    )
    return {
        "backend_postgres": "confirmed_by_db_session",
        "tenant_id": str(TENANT_ID),
        "deployment_id": str(deployment.id),
        "publish_state": deployment.publish_state,
        "runtime_mode": deployment.runtime_mode,
        "environment": deployment.environment,
        "channel": deployment.channel,
        "respond_style_enabled": bool(metadata.get("respond_style_enabled")),
        "respond_style_inbound_shadow_enabled": bool(
            metadata.get("respond_style_inbound_shadow_enabled")
        ),
        "allowlist": metadata.get("respond_style_inbound_shadow_allowed_phones"),
        "allowlist_contains_phone": ALLOWLIST_PHONE
        in [str(item) for item in metadata.get("respond_style_inbound_shadow_allowed_phones") or []],
        "model": metadata.get("respond_style_model"),
        "model_is_expected": metadata.get("respond_style_model") == EXPECTED_MODEL,
        "outbox_pending_retry_initial": outbox_pending_retry,
        "shadow_state_rows_for_phone_initial": state_rows,
        "customer_id": str(customer.id),
        "customer_phone": customer.phone_e164,
    }


async def _state_before(session: Any) -> dict[str, Any]:
    customer = await _customer(session)
    rows = (
        await session.execute(
            text(
                """
                SELECT c.id, c.status, c.current_stage, c.channel, c.last_activity_at,
                       COALESCE(cs.bot_paused, false) AS bot_paused
                FROM conversations c
                LEFT JOIN conversation_state cs ON cs.conversation_id = c.id
                WHERE c.tenant_id = :tenant_id
                  AND c.customer_id = :customer_id
                  AND c.deleted_at IS NULL
                ORDER BY c.last_activity_at DESC
                LIMIT 5
                """
            ),
            {"tenant_id": TENANT_ID, "customer_id": customer.id},
        )
    ).mappings().all()
    shadow_rows = (
        await session.execute(
            text(
                """
                SELECT sf.conversation_id, sf.field_values,
                       jsonb_array_length(sf.audit_log) AS audit_items, sf.updated_at
                FROM respond_style_shadow_fields sf
                JOIN conversations c ON c.id = sf.conversation_id
                WHERE sf.tenant_id = :tenant_id
                  AND c.customer_id = :customer_id
                ORDER BY sf.updated_at DESC
                """
            ),
            {"tenant_id": TENANT_ID, "customer_id": customer.id},
        )
    ).mappings().all()
    return {
        "recent_conversations": [_jsonable(dict(row)) for row in rows],
        "shadow_fields": [_jsonable(dict(row)) for row in shadow_rows],
    }


async def _baselines(session: Any) -> dict[str, int]:
    return {
        "outbox_rows": await _scalar(session, "SELECT COUNT(*) FROM outbound_outbox"),
        "outbox_pending_retry": await _scalar(
            session,
            "SELECT COUNT(*) FROM outbound_outbox WHERE status IN ('pending','retry')",
        ),
        "action_logs": await _scalar(
            session,
            "SELECT COUNT(*) FROM action_execution_logs WHERE tenant_id = :tenant_id",
            {"tenant_id": TENANT_ID},
        ),
        "human_handoffs": await _scalar(
            session,
            "SELECT COUNT(*) FROM human_handoffs WHERE tenant_id = :tenant_id",
            {"tenant_id": TENANT_ID},
        ),
        "turn_traces_shadow": await _scalar(
            session,
            """
            SELECT COUNT(*) FROM turn_traces
            WHERE tenant_id = :tenant_id
              AND router_trigger = :router_trigger
            """,
            {"tenant_id": TENANT_ID, "router_trigger": SHADOW_ROUTER_TRIGGER},
        ),
    }


async def _postchecks(
    session: Any,
    *,
    baselines: dict[str, int],
    conversation_ids: list[UUID],
) -> dict[str, Any]:
    trace_count = await _scalar(
        session,
        """
        SELECT COUNT(*) FROM turn_traces
        WHERE tenant_id = :tenant_id
          AND router_trigger = :router_trigger
          AND conversation_id = ANY(:conversation_ids)
        """,
        {
            "tenant_id": TENANT_ID,
            "router_trigger": SHADOW_ROUTER_TRIGGER,
            "conversation_ids": conversation_ids,
        },
    )
    outbox_rows = await _scalar(session, "SELECT COUNT(*) FROM outbound_outbox")
    outbox_pending_retry = await _scalar(
        session,
        "SELECT COUNT(*) FROM outbound_outbox WHERE status IN ('pending','retry')",
    )
    action_logs_for_conversations = await _scalar(
        session,
        """
        SELECT COUNT(*) FROM action_execution_logs
        WHERE tenant_id = :tenant_id
          AND conversation_id = ANY(:conversation_ids)
        """,
        {"tenant_id": TENANT_ID, "conversation_ids": conversation_ids},
    )
    workflows_for_conversations = await _scalar(
        session,
        """
        SELECT COUNT(*) FROM workflow_executions
        WHERE conversation_id = ANY(:conversation_ids)
        """,
        {"conversation_ids": conversation_ids},
    )
    handoffs_for_conversations = await _scalar(
        session,
        """
        SELECT COUNT(*) FROM human_handoffs
        WHERE tenant_id = :tenant_id
          AND conversation_id = ANY(:conversation_ids)
        """,
        {"tenant_id": TENANT_ID, "conversation_ids": conversation_ids},
    )
    return {
        "shadow_trace_count_for_harness": trace_count,
        "expected_shadow_trace_count": len(ALL_TURNS),
        "outbox_rows_after": outbox_rows,
        "outbox_delta": outbox_rows - baselines["outbox_rows"],
        "outbox_pending_retry_after": outbox_pending_retry,
        "action_logs_for_harness_conversations": action_logs_for_conversations,
        "workflow_executions_for_harness_conversations": workflows_for_conversations,
        "human_handoffs_for_harness_conversations": handoffs_for_conversations,
    }


async def _create_harness_conversation(
    session: Any, run_id: str, window: str
) -> Conversation:
    customer = await _customer(session)
    conversation = Conversation(
        id=uuid4(),
        tenant_id=TENANT_ID,
        customer_id=customer.id,
        channel="whatsapp",
        status="active",
        current_stage="nuevos",
        tags=[
            "codex_harness",
            "respond_style_window_6",
            "simulated_inbound_shadow",
            window,
        ],
    )
    session.add(conversation)
    await session.flush()
    session.add(
        ConversationStateRow(
            conversation_id=conversation.id,
            extracted_data={},
            bot_paused=False,
        )
    )
    await session.flush()
    return conversation


async def _run_turn(
    session: Any,
    *,
    run_id: str,
    conversation_id: UUID,
    turn: HarnessTurn,
) -> dict[str, Any]:
    before_state = await _shadow_state(session, conversation_id)
    outbox_before = await _scalar(session, "SELECT COUNT(*) FROM outbound_outbox")
    now = datetime.now(UTC)
    message_id = uuid4()
    metadata: dict[str, Any] = {
        "codex_harness_run_id": run_id,
        "simulated_inbound_shadow": True,
        "respond_style_window": "window_6",
        "window": turn.window,
        "turn_number": turn.turn_number,
    }
    if turn.media_type:
        metadata["media"] = {
            "type": "image",
            "mime_type": turn.media_type,
            "caption": None,
            "simulated_no_bytes": True,
        }
    session.add(
        MessageRow(
            id=message_id,
            conversation_id=conversation_id,
            tenant_id=TENANT_ID,
            direction="inbound",
            text=turn.text,
            channel_message_id=f"{run_id}:{turn.turn_number}",
            sent_at=now,
            metadata_json=metadata,
        )
    )
    await session.flush()

    summaries = await run_inbound_shadow(
        session,
        tenant_id=TENANT_ID,
        conversation_id=conversation_id,
        inbound_text=turn.text,
        inbound_message_id=message_id,
        from_phone_e164=FROM_PHONE_E164,
    )
    summary = summaries[0] if summaries else {}
    candidate = summary.get("final_message_candidate")
    if candidate:
        session.add(
            MessageRow(
                id=uuid4(),
                conversation_id=conversation_id,
                tenant_id=TENANT_ID,
                direction="outbound",
                text=candidate,
                sent_at=datetime.now(UTC),
                metadata_json={
                    "codex_harness_run_id": run_id,
                    "simulated_no_send": True,
                    "assistant_shadow_transcript_only": True,
                    "respond_style_window": "window_6",
                    "window": turn.window,
                    "source_inbound_message_id": str(message_id),
                },
            )
        )
        await session.flush()

    trace_row = (
        await session.execute(
            text(
                """
                SELECT id, created_at, composer_model, composer_output, raw_llm_response,
                       kb_evidence, state_before, state_after, errors, rules_evaluated
                FROM turn_traces
                WHERE tenant_id = :tenant_id
                  AND conversation_id = :conversation_id
                  AND inbound_message_id = :message_id
                  AND router_trigger = :router_trigger
                ORDER BY created_at DESC
                LIMIT 1
                """
            ),
            {
                "tenant_id": TENANT_ID,
                "conversation_id": conversation_id,
                "message_id": message_id,
                "router_trigger": SHADOW_ROUTER_TRIGGER,
            },
        )
    ).mappings().first()
    after_state = await _shadow_state(session, conversation_id)
    outbox_after = await _scalar(session, "SELECT COUNT(*) FROM outbound_outbox")
    evidence = _build_turn_evidence(
        turn=turn,
        message_id=message_id,
        trace_row=dict(trace_row) if trace_row else {},
        summary=summary,
        before_state=before_state,
        after_state=after_state,
        outbox_delta=outbox_after - outbox_before,
    )
    return evidence


def _build_turn_evidence(
    *,
    turn: HarnessTurn,
    message_id: UUID,
    trace_row: dict[str, Any],
    summary: dict[str, Any],
    before_state: dict[str, Any],
    after_state: dict[str, Any],
    outbox_delta: int,
) -> dict[str, Any]:
    field_state = summary.get("field_state") or {}
    side_effects = summary.get("side_effects") or {}
    tools = summary.get("tools") or []
    validator = summary.get("validator") or {}
    failures = _turn_failures(
        turn=turn,
        summary=summary,
        before_state=before_state,
        after_state=after_state,
        tools=tools,
        validator=validator,
        outbox_delta=outbox_delta,
    )
    score = _score_turn(turn=turn, summary=summary, failures=failures)
    return {
        "turn_number": turn.turn_number,
        "window": turn.window,
        "timestamp": str(trace_row.get("created_at") or ""),
        "inbound_text": turn.text,
        "media_type": turn.media_type,
        "inbound_message_id": str(message_id),
        "turn_trace_id": str(trace_row.get("id") or summary.get("turn_trace_id") or ""),
        "router_trigger": SHADOW_ROUTER_TRIGGER if trace_row else None,
        "final_message_candidate": summary.get("final_message_candidate"),
        "send_decision": summary.get("send_decision"),
        "model": EXPECTED_MODEL,
        "tools": tools,
        "tool_results": tools,
        "field_updates": {
            "proposed": summary.get("field_update_proposals") or [],
            "applied": _audit_by_status(field_state, "accepted"),
            "rejected": _audit_by_status(field_state, "rejected"),
            "audit": field_state.get("audit") or [],
        },
        "validator_result": validator,
        "retry_count": _retry_count(summary),
        "claims_source_refs": _claims_source_refs(summary, trace_row),
        "selected_model_before": before_state.get("field_values", {}).get("selected_model"),
        "selected_model_after": after_state.get("field_values", {}).get("selected_model"),
        "income_type_before": before_state.get("field_values", {}).get("income_type"),
        "income_type_after": after_state.get("field_values", {}).get("income_type"),
        "handoff_pending": _handoff_pending(summary),
        "handoff_proposal": summary.get("handoff_proposal"),
        "legacy_path_used": summary.get("legacy_path_used"),
        "outbox_writes": outbox_delta,
        "side_effects": side_effects,
        "score": score,
        "failures": failures,
        "raw_summary": summary,
    }


def _turn_failures(
    *,
    turn: HarnessTurn,
    summary: dict[str, Any],
    before_state: dict[str, Any],
    after_state: dict[str, Any],
    tools: list[dict[str, Any]],
    validator: dict[str, Any],
    outbox_delta: int,
) -> list[str]:
    failures: list[str] = []
    candidate = str(summary.get("final_message_candidate") or "")
    candidate_l = _norm(candidate)
    inbound_l = _norm(turn.text)
    if not candidate:
        failures.append("no_final_message_candidate")
    if summary.get("send_decision") != "no_send":
        failures.append("send_decision_not_no_send")
    if summary.get("legacy_path_used") is not False:
        failures.append("legacy_path_used")
    if outbox_delta != 0 or summary.get("outbox_write_attempted") is not False:
        failures.append("outbox_write")
    if any(bool(v) for v in (summary.get("side_effects") or {}).values()):
        failures.append("side_effects")
    if _unsupported_claim_validator(validator):
        failures.append("unsupported_claims")
    if _annotated_value_accepted(summary):
        failures.append("annotated_field_value_accepted")
    if _invalid_selected_model_accepted(before_state, after_state, summary):
        failures.append("invalid_selected_model_accepted")
    if turn.media_type:
        if any(word in candidate_l for word in ("catalogo", "manejamos", "cotizacion", "enganche")):
            failures.append("media_hallucination")
        if not any(word in candidate_l for word in ("imagen", "foto", "muestra", "modelo", "contexto")):
            failures.append("media_missing_context_request")
    if turn.turn_number != 20 and (summary.get("handoff_proposal") or {}).get("needed"):
        failures.append("premature_handoff_proposal")
    if turn.turn_number != 20 and _handoff_like(summary, candidate_l):
        if any(
            word in inbound_l
            for word in ("info", "motos", "catalogo", "cuanto", "plan", "ocupo", "caro", "barata")
        ):
            failures.append("handoff_cascade")
    if turn.turn_number == 20 and not _handoff_like(summary, candidate_l):
        failures.append("handoff_missing_on_explicit_request")
    if any(word in inbound_l for word in ("cuanto queda", "cuanto doy", "caro", "barata")):
        if not _has_tool(tools, {"quote.resolve", "catalog.search", "eligibility_plan.resolve", "credit_plan.resolve", "requirements.lookup"}):
            if any(char.isdigit() for char in candidate):
                failures.append("price_without_tool_or_kb")
    if any(word in inbound_l for word in ("ocupo", "papeles", "documentos", "resibos")):
        if "requis" in candidate_l and not _has_tool(tools, {"requirements.lookup"}):
            failures.append("requirements_without_tool_or_kb")
    return failures


def _score_turn(
    *,
    turn: HarnessTurn,
    summary: dict[str, Any],
    failures: list[str],
) -> float:
    if any(item in failures for item in ("legacy_path_used", "outbox_write", "side_effects")):
        return 1.0
    if not summary.get("final_message_candidate"):
        return 2.0
    score = 5.0
    severe = {
        "unsupported_claims",
        "invalid_selected_model_accepted",
        "annotated_field_value_accepted",
        "media_hallucination",
        "price_without_tool_or_kb",
        "requirements_without_tool_or_kb",
        "handoff_cascade",
        "premature_handoff_proposal",
    }
    for failure in failures:
        score -= 1.5 if failure in severe else 0.75
    if turn.critical and failures:
        score = min(score, 3.5)
    return max(1.0, round(score, 2))


def _render_report(
    *,
    run_id: str,
    prechecks: dict[str, Any],
    state_before: dict[str, Any],
    baselines: dict[str, int],
    postchecks: dict[str, Any],
    main_conversation_id: str,
    orthography_conversation_id: str,
    final_state_main: dict[str, Any],
    final_state_orthography: dict[str, Any],
    turns: list[dict[str, Any]],
) -> str:
    hard_checks = _hard_checks(turns, prechecks, postchecks)
    decision = _decision(hard_checks, turns)
    avg_score = round(sum(float(turn["score"]) for turn in turns) / len(turns), 2)
    main_turns = [turn for turn in turns if turn["window"] == "main"]
    main_avg = round(sum(float(turn["score"]) for turn in main_turns) / len(main_turns), 2)
    critical_min = min(float(turn["score"]) for turn in turns if _is_critical(turn))
    lines: list[str] = []
    lines.append("# Respond-Style Window 6 Harness Execution")
    lines.append("")
    lines.append(f"Date: {REPORT_DATE}")
    lines.append(f"Run id: `{run_id}`")
    lines.append(f"Mode: `simulated_inbound_shadow`")
    lines.append(f"Tenant: `{TENANT_ID}`")
    lines.append(f"Deployment: `{DEPLOYMENT_ID}`")
    lines.append(f"Main conversation: `{main_conversation_id}`")
    lines.append(f"Orthography mini-window conversation: `{orthography_conversation_id}`")
    lines.append(f"Router trigger expected/observed: `{SHADOW_ROUTER_TRIGGER}`")
    lines.append("")
    lines.append("## 1. Resumen ejecutivo")
    lines.append("")
    lines.append(
        f"Se ejecuto un harness marcado como `simulated_inbound_shadow` usando "
        f"`run_inbound_shadow`, el mismo hook que el pipeline Baileys invoca en "
        f"step 2c. No se uso el endpoint Baileys completo porque evalua workflows "
        f"antes del shadow. Resultado: decision **`{decision}`**, score promedio "
        f"general **{avg_score}**, score promedio main **{main_avg}**, minimo "
        f"critico **{critical_min}**."
    )
    lines.append("")
    lines.append("## 2. Tabla turno por turno")
    lines.append("")
    lines.append(
        "| # | Window | Inbound/media | Candidate | Tools | Fields | Handoff | Score | Fallo |"
    )
    lines.append("|---:|---|---|---|---|---|---|---:|---|")
    for turn in turns:
        fields = turn["field_updates"]
        field_summary = (
            f"A:{len(fields['applied'])}/R:{len(fields['rejected'])}; "
            f"model {turn['selected_model_before']} -> {turn['selected_model_after']}; "
            f"income {turn['income_type_before']} -> {turn['income_type_after']}"
        )
        lines.append(
            "| {n} | {window} | {inbound} | {candidate} | {tools} | {fields} | {handoff} | {score} | {failures} |".format(
                n=turn["turn_number"],
                window=turn["window"],
                inbound=_md(_short(turn["inbound_text"], 90)),
                candidate=_md(_short(turn.get("final_message_candidate") or "", 180)),
                tools=_md(_tool_names(turn["tools"])),
                fields=_md(field_summary),
                handoff=_md(_handoff_text(turn)),
                score=turn["score"],
                failures=_md(", ".join(turn["failures"]) if turn["failures"] else "none"),
            )
        )
    lines.append("")
    lines.append("## 3. Score por turno")
    lines.append("")
    lines.append(
        ", ".join(
            f"t{turn['turn_number']}={turn['score']}" for turn in turns
        )
    )
    lines.append("")
    lines.append(f"Promedio general: **{avg_score}**. Promedio main: **{main_avg}**.")
    lines.append("")
    lines.append("## 4. Checks duros")
    lines.append("")
    for key, value in hard_checks.items():
        lines.append(f"- `{key}`: `{value}`")
    lines.append("")
    lines.append("## 5. Estado final")
    lines.append("")
    lines.append("Main shadow state:")
    lines.append("")
    lines.append("```json")
    lines.append(json.dumps(final_state_main, indent=2, ensure_ascii=False, default=str))
    lines.append("```")
    lines.append("")
    lines.append("Orthography shadow state:")
    lines.append("")
    lines.append("```json")
    lines.append(json.dumps(final_state_orthography, indent=2, ensure_ascii=False, default=str))
    lines.append("```")
    lines.append("")
    lines.append("State before allowlisted phone:")
    lines.append("")
    lines.append("```json")
    lines.append(json.dumps(state_before, indent=2, ensure_ascii=False, default=str))
    lines.append("```")
    lines.append("")
    lines.append("## 6. Tools usadas")
    lines.append("")
    for name, count in sorted(_tools_used(turns).items()):
        lines.append(f"- `{name}`: {count}")
    if not _tools_used(turns):
        lines.append("- none")
    lines.append("")
    lines.append("## 7. Field audit")
    lines.append("")
    for turn in turns:
        audit = turn["field_updates"]["audit"]
        if not audit:
            continue
        lines.append(f"Turn {turn['turn_number']}:")
        lines.append("")
        lines.append("```json")
        lines.append(json.dumps(audit, indent=2, ensure_ascii=False, default=str))
        lines.append("```")
        lines.append("")
    lines.append("## 8. Handoff audit")
    lines.append("")
    for turn in turns:
        if turn.get("handoff_pending") or turn.get("handoff_proposal"):
            lines.append(
                f"- t{turn['turn_number']}: pending={turn.get('handoff_pending')} proposal="
                f"`{json.dumps(turn.get('handoff_proposal'), ensure_ascii=False, default=str)}`"
            )
    lines.append("")
    lines.append("## 9. Fallos clasificados")
    lines.append("")
    classified = _classified_failures(turns)
    if classified:
        for failure, refs in sorted(classified.items()):
            lines.append(f"- `{failure}`: {', '.join(refs)}")
    else:
        lines.append("- none")
    lines.append("")
    lines.append("## 10. Decision final")
    lines.append("")
    lines.append(f"`{decision}`")
    lines.append("")
    lines.append("## Evidence payload")
    lines.append("")
    lines.append("```json")
    lines.append(
        json.dumps(
            {
                "prechecks": prechecks,
                "baselines": baselines,
                "postchecks": postchecks,
                "turns": turns,
            },
            indent=2,
            ensure_ascii=False,
            default=str,
        )
    )
    lines.append("```")
    return "\n".join(lines)


def _hard_checks(
    turns: list[dict[str, Any]],
    prechecks: dict[str, Any],
    postchecks: dict[str, Any],
) -> dict[str, Any]:
    avg = round(sum(float(turn["score"]) for turn in turns) / len(turns), 2)
    critical_scores = [float(turn["score"]) for turn in turns if _is_critical(turn)]
    failures = _classified_failures(turns)
    return {
        "prechecks_passed": all(
            [
                prechecks.get("publish_state") == "published_no_send",
                prechecks.get("respond_style_enabled") is True,
                prechecks.get("respond_style_inbound_shadow_enabled") is True,
                prechecks.get("allowlist_contains_phone") is True,
                prechecks.get("outbox_pending_retry_initial") == 0,
                prechecks.get("model_is_expected") is True,
            ]
        ),
        "average_score_ge_4_2": avg >= 4.2,
        "no_critical_turn_below_4": min(critical_scores or [0]) >= 4.0,
        "zero_unsupported_claims": "unsupported_claims" not in failures,
        "zero_invalid_selected_model_accepted": "invalid_selected_model_accepted" not in failures,
        "zero_annotated_field_values_accepted": "annotated_field_value_accepted" not in failures,
        "zero_handoff_cascade": "handoff_cascade" not in failures,
        "zero_premature_handoff_proposal": "premature_handoff_proposal" not in failures,
        "zero_media_hallucination": "media_hallucination" not in failures,
        "zero_price_or_requirements_without_tool_or_kb": not (
            "price_without_tool_or_kb" in failures
            or "requirements_without_tool_or_kb" in failures
        ),
        "zero_legacy_path_used": all(turn["legacy_path_used"] is False for turn in turns),
        "zero_outbox": postchecks.get("outbox_delta") == 0
        and postchecks.get("outbox_pending_retry_after") == 0
        and all(turn["outbox_writes"] == 0 for turn in turns),
        "zero_side_effects": postchecks.get("action_logs_for_harness_conversations") == 0
        and postchecks.get("workflow_executions_for_harness_conversations") == 0
        and postchecks.get("human_handoffs_for_harness_conversations") == 0
        and all(not any((turn.get("side_effects") or {}).values()) for turn in turns),
        "trace_count_matches": postchecks.get("shadow_trace_count_for_harness")
        == postchecks.get("expected_shadow_trace_count"),
        "all_router_trigger_respond_style": all(
            turn.get("router_trigger") == SHADOW_ROUTER_TRIGGER for turn in turns
        ),
    }


def _decision(hard_checks: dict[str, Any], turns: list[dict[str, Any]]) -> str:
    failures = _classified_failures(turns)
    if "annotated_field_value_accepted" in failures:
        return "BLOCKED_BY_ALLOWED_VALUES_RETRY"
    if "handoff_cascade" in failures or "premature_handoff_proposal" in failures:
        return "BLOCKED_BY_HANDOFF_CASCADE"
    if "media_hallucination" in failures:
        return "BLOCKED_BY_MEDIA_HALLUCINATION"
    if "invalid_selected_model_accepted" in failures:
        return "BLOCKED_BY_INVALID_MODEL_WRITE"
    if "unsupported_claims" in failures:
        return "BLOCKED_BY_UNSUPPORTED_CLAIMS"
    if (
        "price_without_tool_or_kb" in failures
        or "requirements_without_tool_or_kb" in failures
    ):
        return "BLOCKED_BY_PRICE_OR_REQUIREMENTS_GROUNDING"
    if all(hard_checks.values()):
        return "SHADOW_WINDOW_6_HARNESS_PASSED_NEEDS_REAL_WHATSAPP_CONFIRMATION"
    return "UNSAFE_TO_SMOKE"


async def _customer(session: Any) -> Customer:
    customer = (
        await session.execute(
            select(Customer)
            .where(Customer.tenant_id == TENANT_ID)
            .where(text("right(regexp_replace(phone_e164, '\\D', '', 'g'), 10) = :phone"))
            .params(phone=ALLOWLIST_PHONE)
            .limit(1)
        )
    ).scalars().first()
    if customer is None:
        raise RuntimeError(f"allowlisted_customer_not_found:{ALLOWLIST_PHONE}")
    return customer


async def _shadow_state(session: Any, conversation_id: UUID) -> dict[str, Any]:
    row = await session.get(RespondStyleShadowFields, conversation_id)
    if row is None:
        return {"field_values": {}, "audit_log": [], "updated_at": None}
    return {
        "field_values": dict(row.field_values or {}),
        "audit_log": list(row.audit_log or []),
        "updated_at": str(row.updated_at),
    }


async def _scalar(
    session: Any,
    sql: str,
    params: dict[str, Any] | None = None,
) -> int:
    return int((await session.execute(text(sql), params or {})).scalar() or 0)


def _jsonable(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def _audit_by_status(field_state: dict[str, Any], status: str) -> list[dict[str, Any]]:
    return [
        item
        for item in field_state.get("audit") or []
        if isinstance(item, dict) and item.get("status") == status
    ]


def _retry_count(summary: dict[str, Any]) -> int:
    retry = summary.get("retry_backoff") or {}
    return int(retry.get("validator_retries_total") or 0) + int(
        retry.get("transient_retries_total") or 0
    )


def _claims_source_refs(summary: dict[str, Any], trace_row: dict[str, Any]) -> dict[str, Any]:
    validator = summary.get("validator") or {}
    return {
        "validator_blocked_items": validator.get("blocked_items") or [],
        "kb_evidence": trace_row.get("kb_evidence") or {},
    }


def _handoff_pending(summary: dict[str, Any]) -> bool:
    no_send = summary.get("no_send_followup") or {}
    return bool(no_send.get("action") == "handoff_internal_needed")


def _handoff_like(summary: dict[str, Any], candidate_l: str) -> bool:
    proposal = summary.get("handoff_proposal") or {}
    return bool(proposal.get("needed")) or any(
        item in candidate_l
        for item in (
            "te conecto",
            "te paso",
            "un momento",
        )
    )


def _handoff_text(turn: dict[str, Any]) -> str:
    proposal = turn.get("handoff_proposal") or {}
    if proposal:
        return f"needed={proposal.get('needed')} target={proposal.get('target')}"
    if turn.get("handoff_pending"):
        return "pending/internal"
    return "none"


def _unsupported_claim_validator(validator: dict[str, Any]) -> bool:
    for item in validator.get("blocked_items") or []:
        code = _norm(str(item.get("code") or ""))
        msg = _norm(str(item.get("message") or ""))
        if any(word in f"{code} {msg}" for word in ("unsupported", "claim", "source_ref", "fuente")):
            return True
    return False


def _annotated_value_accepted(summary: dict[str, Any]) -> bool:
    for item in _audit_by_status(summary.get("field_state") or {}, "accepted"):
        value = str(item.get("new_value") or item.get("value") or "")
        field_key = str(item.get("field_key") or "")
        if field_key == "income_type" and ("(" in value or ")" in value):
            return True
    return False


def _invalid_selected_model_accepted(
    before_state: dict[str, Any],
    after_state: dict[str, Any],
    summary: dict[str, Any],
) -> bool:
    before = before_state.get("field_values", {}).get("selected_model")
    after = after_state.get("field_values", {}).get("selected_model")
    if after is None or after == before:
        return False
    accepted_models = {"metro", "motociclo metro", "dinamo metro"}
    raw = _norm(str(after))
    accepted = any(item in raw for item in accepted_models)
    if accepted:
        return False
    for item in _audit_by_status(summary.get("field_state") or {}, "accepted"):
        if item.get("field_key") == "selected_model":
            return True
    return False


def _has_tool(tools: list[dict[str, Any]], names: set[str]) -> bool:
    for item in tools:
        if item.get("tool_name") in names and item.get("status") == "succeeded":
            return True
    return False


def _tool_names(tools: list[dict[str, Any]]) -> str:
    if not tools:
        return "none"
    return ", ".join(
        f"{item.get('tool_name')}:{item.get('status')}" for item in tools
    )


def _tools_used(turns: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for turn in turns:
        for item in turn.get("tools") or []:
            name = item.get("tool_name") or "unknown"
            counts[name] = counts.get(name, 0) + 1
    return counts


def _classified_failures(turns: list[dict[str, Any]]) -> dict[str, list[str]]:
    failures: dict[str, list[str]] = {}
    for turn in turns:
        for failure in turn.get("failures") or []:
            failures.setdefault(failure, []).append(f"t{turn['turn_number']}")
    return failures


def _is_critical(turn: dict[str, Any]) -> bool:
    return any(item.turn_number == turn["turn_number"] and item.critical for item in ALL_TURNS)


def _norm(value: str) -> str:
    value = value.casefold()
    replacements = str.maketrans("áéíóúüñ", "aeiouun")
    return value.translate(replacements)


def _short(value: str, limit: int) -> str:
    value = re.sub(r"\s+", " ", value or "").strip()
    if len(value) <= limit:
        return value
    return value[: limit - 3].rstrip() + "..."


def _md(value: str) -> str:
    return (value or "").replace("|", "\\|").replace("\n", " ")


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
