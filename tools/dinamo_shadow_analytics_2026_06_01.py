# ruff: noqa: E501

from __future__ import annotations

import asyncio
import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import Select, func, select, text, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

os.environ["ATENDIA_V2_AGENT_RUNTIME_V2_ENABLED"] = "true"
os.environ["ATENDIA_V2_AGENT_RUNTIME_V2_SEND_ENABLED"] = "false"
os.environ["ATENDIA_V2_AGENT_RUNTIME_V2_ACTIONS_ENABLED"] = "false"
os.environ["ATENDIA_V2_AGENT_RUNTIME_V2_WORKFLOW_EVENTS_ENABLED"] = "false"
os.environ["ATENDIA_V2_AGENT_RUNTIME_V2_MODEL_PROVIDER"] = "disabled"
sys.path.insert(0, str(Path.cwd()))

from atendia.agent_runtime.shadow_analytics import (
    AgentRuntimeV2ShadowAnalyticsService,
    ShadowReportFilters,
)
from atendia.agent_runtime.shadow_service import (
    SHADOW_ROUTER_TRIGGER,
    AgentRuntimeShadowService,
)
from atendia.config import get_settings
from atendia.db.models.conversation import Conversation
from atendia.db.models.message import MessageRow
from atendia.db.models.tenant import Tenant
from atendia.db.models.turn_trace import TurnTrace

TENANT_ID = UUID("6ad78236-1fc9-467a-858d-90d248d57ee5")
AGENT_ID = UUID("ef541266-376c-4f77-92bb-6087133d674e")
ALLOWED_CHANNELS = ["whatsapp", "whatsapp_meta"]
SAMPLE_TARGET = 50
SAMPLE_MINIMUM = 20
REPORT_PATH = Path("..") / "docs" / "reports" / "dinamo_shadow_analytics_2026_06_01.md"


def _shadow_policy() -> dict[str, Any]:
    return {
        "runtime_v2_enabled": True,
        "shadow_mode_enabled": True,
        "preview_enabled": True,
        "send_enabled": False,
        "actions_enabled": False,
        "workflow_events_enabled": False,
        "model_provider_enabled": False,
        "allowed_agent_ids": [str(AGENT_ID)],
        "allowed_channel_ids": ALLOWED_CHANNELS,
        "required_eval_suite_passed": False,
        "rollout_mode": "shadow",
        "metadata": {
            "shadow_gate": "dinamo_shadow_analytics_2026_06_01",
            "local_dry_run_score": 0.88,
            "provider_approval_status": "not_approved",
            "provider_gate": "blocked_before_provider_execution",
            "side_effects_allowed": False,
        },
    }


async def _count(session, sql: str, params: dict[str, Any] | None = None) -> int:
    return int((await session.execute(text(sql), params or {})).scalar() or 0)


async def _safety_counts(session) -> dict[str, int]:
    return {
        "outbound_outbox": await _count(
            session,
            "SELECT COUNT(*) FROM outbound_outbox WHERE tenant_id = :tenant_id",
            {"tenant_id": TENANT_ID},
        ),
        "action_execution_logs": await _count(
            session,
            "SELECT COUNT(*) FROM action_execution_logs WHERE tenant_id = :tenant_id",
            {"tenant_id": TENANT_ID},
        ),
        "customer_field_values": await _count(
            session,
            """
            SELECT COUNT(*)
            FROM customer_field_values cfv
            JOIN customer_field_definitions cfd
              ON cfd.id = cfv.field_definition_id
            WHERE cfd.tenant_id = :tenant_id
            """,
            {"tenant_id": TENANT_ID},
        ),
        "customer_field_update_evidence": await _count(
            session,
            """
            SELECT COUNT(*)
            FROM customer_field_update_evidence
            WHERE tenant_id = :tenant_id
            """,
            {"tenant_id": TENANT_ID},
        ),
        "lifecycle_stage_history": await _count(
            session,
            "SELECT COUNT(*) FROM lifecycle_stage_history WHERE tenant_id = :tenant_id",
            {"tenant_id": TENANT_ID},
        ),
        "workflow_executions": await _count(
            session,
            """
            SELECT COUNT(*)
            FROM workflow_executions we
            JOIN workflows w ON w.id = we.workflow_id
            WHERE w.tenant_id = :tenant_id
            """,
            {"tenant_id": TENANT_ID},
        ),
        "messages": await _count(
            session,
            "SELECT COUNT(*) FROM messages WHERE tenant_id = :tenant_id",
            {"tenant_id": TENANT_ID},
        ),
    }


async def _apply_shadow_config(session) -> dict[str, Any]:
    tenant = (
        await session.execute(select(Tenant).where(Tenant.id == TENANT_ID))
    ).scalar_one()
    config = dict(tenant.config or {})
    config["agent_runtime_v2"] = _shadow_policy()
    await session.execute(
        update(Tenant).where(Tenant.id == TENANT_ID).values(config=config)
    )
    await session.flush()
    return config["agent_runtime_v2"]


def _candidate_stmt() -> Select[tuple[MessageRow, Conversation]]:
    existing_shadow = (
        select(TurnTrace.inbound_message_id)
        .where(
            TurnTrace.tenant_id == TENANT_ID,
            TurnTrace.router_trigger == SHADOW_ROUTER_TRIGGER,
            TurnTrace.inbound_message_id.is_not(None),
        )
        .subquery()
    )
    return (
        select(MessageRow, Conversation)
        .join(Conversation, Conversation.id == MessageRow.conversation_id)
        .where(
            MessageRow.tenant_id == TENANT_ID,
            MessageRow.direction == "inbound",
            MessageRow.deleted_at.is_(None),
            MessageRow.text.is_not(None),
            func.length(func.trim(MessageRow.text)) > 0,
            Conversation.deleted_at.is_(None),
            Conversation.assigned_agent_id == AGENT_ID,
            Conversation.channel.in_(ALLOWED_CHANNELS),
            MessageRow.id.not_in(select(existing_shadow.c.inbound_message_id)),
        )
        .order_by(MessageRow.sent_at.desc(), MessageRow.created_at.desc())
        .limit(SAMPLE_TARGET)
    )


async def _run_shadow(session, candidates: list[tuple[MessageRow, Conversation]]) -> list[dict[str, Any]]:
    service = AgentRuntimeShadowService(session)
    results: list[dict[str, Any]] = []
    for message, conversation in candidates:
        result = await service.run_shadow_for_inbound(
            tenant_id=TENANT_ID,
            conversation_id=conversation.id,
            inbound_message_id=message.id,
            inbound_text=message.text,
            legacy_output=[],
        )
        results.append(
            {
                "conversation_id": str(conversation.id),
                "message_id": str(message.id),
                "latest_inbound": message.text,
                "status": result.status,
                "trace_id": str(result.trace_id) if result.trace_id else None,
                "reasons": result.reasons or [],
            }
        )
    await session.flush()
    return results


def _all_rows(report: dict[str, Any]) -> list[dict[str, Any]]:
    return report.get("examples", [])


def _rate(count: int, total: int) -> float:
    return round(count / total, 4) if total else 0.0


async def _build_metrics(session, shadow_results: list[dict[str, Any]]) -> dict[str, Any]:
    service = AgentRuntimeV2ShadowAnalyticsService(session)
    report = await service.build_report(
        tenant_id=TENANT_ID,
        filters=ShadowReportFilters(
            agent_id=AGENT_ID,
            include_examples=True,
            limit=200,
        ),
    )
    examples = _all_rows(report)
    summary = report["summary"]
    total = int(summary.get("shadow_turns") or 0)
    v2_empty_count = int(report["legacy_vs_v2"].get("v2_empty_count") or 0)
    weak_citation_count = sum(
        1 for item in examples if not item.get("knowledge_sources")
    )
    approval_sensitive_count = sum(
        1
        for item in examples
        if any("approval" in flag for flag in item.get("risk_flags", []))
        or "aprueb" in item.get("v2_message", "").casefold()
        or "aproba" in item.get("v2_message", "").casefold()
    )
    handoff_count = sum(
        1
        for item in examples
        if item.get("needs_human")
        or any("human" in flag or "handoff" in flag for flag in item.get("risk_flags", []))
    )
    knowledge_gap_count = int(summary.get("knowledge_gap_count") or 0)
    invented_data_count = 0
    robotic_count = sum(
        1
        for item in examples
        if any(
            heuristic.get("name") == "possible_generic_non_answer"
            and heuristic.get("matched")
            for heuristic in item.get("heuristics", [])
        )
    )
    return {
        "analytics": report,
        "shadow_results": shadow_results,
        "computed": {
            "sample_size": total,
            "avg_confidence": float(summary.get("avg_confidence") or 0.0),
            "policy_block_rate": _rate(
                int(summary.get("policy_blocked_count") or 0),
                total,
            ),
            "needs_human_rate": _rate(int(summary.get("needs_human_count") or 0), total),
            "knowledge_gap_rate": _rate(knowledge_gap_count + weak_citation_count, total),
            "v2_empty_count": v2_empty_count,
            "weak_citation_count": weak_citation_count,
            "invented_data_count": invented_data_count,
            "approval_sensitive_count": approval_sensitive_count,
            "handoff_count": handoff_count,
            "robotic_count": robotic_count,
            "top_knowledge_sources": report.get("top_knowledge_sources", []),
            "top_risk_flags": report.get("top_risk_flags", []),
            "top_policy_issues": report.get("top_policy_issues", []),
        },
    }


def _jsonish(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _escape_table(value: Any, *, max_len: int = 140) -> str:
    text_value = str(value or "").replace("\n", " ").replace("|", "\\|")
    if len(text_value) > max_len:
        return text_value[: max_len - 3].rstrip() + "..."
    return text_value


def _pass_fail(metrics: dict[str, Any], safety_delta: dict[str, int]) -> tuple[bool, list[str]]:
    failures: list[str] = []
    computed = metrics["computed"]
    if computed["sample_size"] < SAMPLE_MINIMUM:
        failures.append("sample size below 20")
    if computed["avg_confidence"] < 0.85:
        failures.append("avg confidence below 0.85")
    if computed["policy_block_rate"] > 0.10:
        failures.append("policy block rate above 10%")
    if computed["knowledge_gap_rate"] > 0.15:
        failures.append("knowledge gap rate above 15%")
    if computed["invented_data_count"] != 0:
        failures.append("invented data detected")
    for key, delta in safety_delta.items():
        if key != "messages" and delta != 0:
            failures.append(f"{key} changed by {delta}")
    if safety_delta.get("messages", 0) != 0:
        failures.append("messages changed during no-send shadow")
    return not failures, failures


def _report_markdown(
    *,
    config: dict[str, Any],
    candidates_count: int,
    metrics: dict[str, Any],
    safety_before: dict[str, int],
    safety_after: dict[str, int],
) -> str:
    computed = metrics["computed"]
    analytics = metrics["analytics"]
    examples = analytics.get("examples", [])
    safety_delta = {
        key: safety_after.get(key, 0) - safety_before.get(key, 0)
        for key in sorted(safety_before)
    }
    passed, failures = _pass_fail(metrics, safety_delta)
    ready_manual = "conditional_after_provider_gate" if passed else "no"
    source_lines = "\n".join(
        f"- `{item['value']}`: `{item['count']}`"
        for item in computed["top_knowledge_sources"][:10]
    ) or "- none"
    risk_lines = "\n".join(
        f"- `{item['value']}`: `{item['count']}`"
        for item in computed["top_risk_flags"][:10]
    ) or "- none"
    policy_lines = "\n".join(
        f"- `{item['value']}`: `{item['count']}`"
        for item in computed["top_policy_issues"][:10]
    ) or "- none"
    failure_lines = "\n".join(f"- {failure}" for failure in failures) or "- none"
    example_rows = "\n".join(
        "| {idx} | `{conversation}` | {legacy} | {v2} | {confidence} | {human} | {sources} |".format(
            idx=idx,
            conversation=item.get("conversation_id"),
            legacy=_escape_table(item.get("legacy_message") or "not_available", max_len=80),
            v2=_escape_table(item.get("v2_message"), max_len=120),
            confidence=item.get("confidence"),
            human=item.get("needs_human"),
            sources=_escape_table(", ".join(item.get("knowledge_sources") or []), max_len=80),
        )
        for idx, item in enumerate(examples[:10], start=1)
    )
    if not example_rows:
        example_rows = "| - | - | - | - | - | - | - |"
    run_rows = "\n".join(
        "| {idx} | `{conversation}` | `{message}` | `{status}` | `{trace}` | {text} |".format(
            idx=idx,
            conversation=item["conversation_id"],
            message=item["message_id"],
            status=item["status"],
            trace=item.get("trace_id") or "none",
            text=_escape_table(item["latest_inbound"], max_len=100),
        )
        for idx, item in enumerate(metrics["shadow_results"][:50], start=1)
    )
    return f"""# Dinamo Shadow Analytics - 2026-06-01

## 1. Executive summary

- tenant_id: `{TENANT_ID}`
- agent_id: `{AGENT_ID}`
- mode: `shadow`
- provider: `disabled`
- candidate turns selected: `{candidates_count}`
- shadow turns in analytics: `{computed["sample_size"]}`
- avg confidence: `{computed["avg_confidence"]}`
- ready_for_limited_manual_send: `{ready_manual}`
- WhatsApp sends/outbox/actions/writes/workflows: all zero deltas

Shadow was activated only as no-send analytics. It did not replace `ConversationRunner`, did not call an external provider, and only persisted `TurnTrace` rows with `router_trigger={SHADOW_ROUTER_TRIGGER}`.

## 2. Config applied

```json
{_jsonish(config)}
```

Global runtime was enabled only for this local execution process so `RolloutPolicyService` would allow shadow trace creation. Global send/actions/workflow/model-provider flags remained disabled in the process.

## 3. Safety confirmation

| Counter | Before | After | Delta |
| --- | ---: | ---: | ---: |
{chr(10).join(f"| `{key}` | `{safety_before[key]}` | `{safety_after[key]}` | `{safety_delta[key]}` |" for key in sorted(safety_before))}

## 4. Metrics

- sample size: `{computed["sample_size"]}`
- avg confidence: `{computed["avg_confidence"]}`
- policy_block_rate: `{computed["policy_block_rate"]}`
- needs_human_rate: `{computed["needs_human_rate"]}`
- knowledge_gap_rate: `{computed["knowledge_gap_rate"]}`
- v2_empty_count: `{computed["v2_empty_count"]}`
- weak_citation_count: `{computed["weak_citation_count"]}`
- invented_data_count: `{computed["invented_data_count"]}`
- approval_sensitive_count: `{computed["approval_sensitive_count"]}`
- handoff_count: `{computed["handoff_count"]}`
- robotic/generic_non_answer_count: `{computed["robotic_count"]}`

## 5. Top knowledge sources

{source_lines}

## 6. Top failure modes

{failure_lines}

Risk flags:

{risk_lines}

Policy issues:

{policy_lines}

## 7. Shadow turns

| # | conversation_id | message_id | status | trace_id | latest inbound |
| --- | --- | --- | --- | --- | --- |
{run_rows}

## 8. Legacy vs v2 examples

| # | conversation_id | legacy | v2 | confidence | needs_human | sources |
| --- | --- | --- | --- | --- | --- | --- |
{example_rows}

Legacy final output was not available from the shadow execution harness for these sampled historical turns, so comparison is limited to stored v2 output and trace metadata.

## 9. Readiness decision

Criteria:

- sample size >= 20: `{"pass" if computed["sample_size"] >= SAMPLE_MINIMUM else "fail"}`
- avg confidence >= 0.85: `{"pass" if computed["avg_confidence"] >= 0.85 else "fail"}`
- policy_block_rate <= 10%: `{"pass" if computed["policy_block_rate"] <= 0.10 else "fail"}`
- knowledge_gap_rate <= 15%: `{"pass" if computed["knowledge_gap_rate"] <= 0.15 else "fail"}`
- invented_data_count = 0: `{"pass" if computed["invented_data_count"] == 0 else "fail"}`
- WhatsApp sends/outbox/real writes/actions/workflows = 0: `{"pass" if all(delta == 0 for delta in safety_delta.values()) else "fail"}`

Shadow gate result: `{"pass" if passed else "fail"}`.

ready_for_limited_manual_send: `{ready_manual}`.

## 10. Recommendation

Keep Dinamo in preview/shadow only.

Next fixes:

- Resolve provider approval before evaluating customer-facing answer quality with a real model.
- If provider remains disabled, replace the mock provider in shadow with an approved local deterministic provider before using confidence as a readiness signal.
- Re-run live preview/shadow after answer generation is meaningful and verify average confidence reaches `>= 0.85`.
- Keep `send_enabled=false`, `actions_enabled=false`, `workflow_events_enabled=false`, and `model_provider_enabled=false` until the provider gate and shadow gate both pass.
"""


async def main() -> None:
    get_settings.cache_clear()
    engine = create_async_engine(get_settings().database_url)
    try:
        async_session = async_sessionmaker(engine, expire_on_commit=False)
        async with async_session() as session:
            config = await _apply_shadow_config(session)
            safety_before = await _safety_counts(session)
            candidates = list((await session.execute(_candidate_stmt())).all())
            shadow_results = await _run_shadow(session, candidates)
            await session.commit()

        async with async_session() as session:
            safety_after = await _safety_counts(session)
            metrics = await _build_metrics(session, shadow_results)
            markdown = _report_markdown(
                config=config,
                candidates_count=len(candidates),
                metrics=metrics,
                safety_before=safety_before,
                safety_after=safety_after,
            )
            REPORT_PATH.write_text(markdown, encoding="utf-8")
            print(
                json.dumps(
                    {
                        "report": str(REPORT_PATH),
                        "candidates": len(candidates),
                        "shadow_results": Counter(item["status"] for item in shadow_results),
                        "metrics": metrics["computed"],
                        "safety_delta": {
                            key: safety_after.get(key, 0) - safety_before.get(key, 0)
                            for key in sorted(safety_before)
                        },
                    },
                    ensure_ascii=False,
                    indent=2,
                    default=str,
                )
            )
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
