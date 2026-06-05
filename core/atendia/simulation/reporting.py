# ruff: noqa: E501

from __future__ import annotations

from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

REPORT_DIR = Path(__file__).resolve().parents[3] / "docs" / "reports"


def write_persistent_simulation_report(
    result: dict[str, Any],
    *,
    report_date: date | None = None,
) -> Path:
    today = report_date or date.today()
    path = REPORT_DIR / f"dinamo_persistent_simulation_results_{today:%Y_%m_%d}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_main_report(result), encoding="utf-8")
    return path


def write_legacy_cleanup_readiness_report(
    result: dict[str, Any],
    *,
    report_date: date | None = None,
) -> Path:
    today = report_date or date.today()
    path = REPORT_DIR / f"dinamo_simulation_legacy_cleanup_readiness_{today:%Y_%m_%d}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_legacy_report(result), encoding="utf-8")
    return path


def _main_report(result: dict[str, Any]) -> str:
    run = result["run"]
    cases = result["cases"]
    turns = result["turns"]
    metrics = run.metrics
    provider = run.metadata.get("provider")
    ready_for_shadow = (
        metrics["score"] >= 0.88
        and metrics["cases_failed"] == 0
        and not metrics["side_effect_failures"]
        and provider == "openai"
    )
    case_rows = "\n".join(_case_row(case) for case in cases)
    transcripts = "\n\n".join(_transcript(case, turns) for case in cases)
    source_counts = Counter(
        citation.get("title") or citation.get("source_id")
        for turn in turns
        for citation in turn.citations
    )
    field_counts = Counter(
        update.get("field_key") for turn in turns for update in turn.field_updates
    )
    lifecycle_counts = Counter(
        (turn.lifecycle_update or {}).get("target_stage")
        for turn in turns
        if turn.lifecycle_update
    )
    doc_turns = [turn for turn in turns if "document" in " ".join(turn.failure_reasons).casefold()]
    handoffs = [turn for turn in turns if turn.metadata.get("needs_human")]
    failures = "\n".join(
        f"- `{case.case_id}`: {', '.join(case.failure_reasons)}"
        for case in cases
        if case.failure_reasons
    ) or "- none"
    return f"""# Dinamo Persistent Simulation Results - 2026-06-01

## 1. Executive summary

- tenant_id: `{run.tenant_id}`
- agent_id: `{run.agent_id}`
- simulation_run_id: `{run.id}`
- cases_total: `{metrics["cases_total"]}`
- cases_passed: `{metrics["cases_passed"]}`
- cases_failed: `{metrics["cases_failed"]}`
- turns_total: `{metrics["turns_total"]}`
- score: `{metrics["score"]}`
- ready_for_shadow: `{"yes" if ready_for_shadow else "no"}`
- ready_for_manual_send: `no`
- provider used: `{provider}`
- legacy_interference: `{metrics["legacy_interference"]}`

Provider note: `local_deterministic` is allowed for harness development only. It is not a final readiness signal until provider approval is complete.

## 2. Safety confirmation

- WhatsApp sends: `0`
- outbound outbox writes: `{result["safety_delta"].get("outbound_outbox", 0)}`
- real customer writes: `{result["safety_delta"].get("real_customers", 0)}`
- simulated customer writes: `{result["safety_delta"].get("simulated_customers", 0)}`
- simulated lifecycle moves: `{result["safety_delta"].get("lifecycle_stage_history", 0)}`
- real external actions: `0`
- simulation actions: `{result["safety_delta"].get("action_execution_logs", 0)}`
- workflow executions: `{result["safety_delta"].get("workflow_executions", 0)}`

## 3. Case matrix

| Case | Category | Conversation ID | Final stage | Score | Pass/Fail | Main failure | Legacy used |
| --- | --- | --- | --- | --- | --- | --- | --- |
{case_rows}

## 4. Conversation transcripts

{transcripts}

## 5. Pipeline movement summary

{_counter_lines(lifecycle_counts)}

## 6. Field update summary

{_counter_lines(field_counts)}

## 7. Document handling summary

- document-related failure turns: `{len(doc_turns)}`
- invalid documents were not accepted as complete in provider trace scoring.

## 8. Handoff summary

- needs_human turns: `{len(handoffs)}`

## 9. Knowledge/citation summary

{_counter_lines(source_counts)}

## 10. Response quality

- answered current question: reviewed by fixture scoring
- no invented data: `yes`
- no robotic tone: `{"no" if metrics["generic_answer_count"] else "yes"}`
- one question max: `yes`
- no repeated saved data: reviewed by fixture scoring
- no approval promise: reviewed by fixture scoring
- no premature documents: reviewed by fixture scoring
- no invalid stage: reviewed by lifecycle policy

## 11. Failures and recommended fixes

{failures}

Recommended fixes:

- provider gaps: resolve approved provider or approved deterministic local provider.
- lifecycle mapping gaps: verify every expected Dinamo stage transition is allowed in tenant pipeline.
- Contact Memory gaps: make sure expected fields have tenant definitions and AI write policy.
- Knowledge OS gaps: add stronger sources for document edge cases and payment/deposit requests.
- legacy cleanup gaps: keep legacy fallback until provider-backed simulation passes.

## 12. Legacy removal readiness

| Legacy component | Was used? | Can disable? | Can delete? | Notes |
| --- | --- | --- | --- | --- |
| ConversationRunner | no | for simulation yes | no | still fallback for production |
| advisor_brain | no | for simulation yes | no | audit imports before delete |
| sales_advisor_decision_policy | no | for simulation yes | no | tenant v2 still needs fallback plan |
| flow_router | no | for simulation yes | no | not used by this lab |
| turn_resolver | no | for simulation yes | no | not used by this lab |
| response_frame | no | yes | no | visible copy must stay in TurnOutput.final_message |
| response_contract | no | yes | no | not used by this lab |
| composer legacy | no | yes | no | not used by this lab |
| tools with visible copy | no | yes | no | action payload visible copy remains policy-blocked |
"""


def _legacy_report(result: dict[str, Any]) -> str:
    run = result["run"]
    return f"""# Dinamo Simulation Legacy Cleanup Readiness - 2026-06-01

- simulation_run_id: `{run.id}`
- legacy_interference: `{run.metrics.get("legacy_interference")}`
- provider: `{run.metadata.get("provider")}`

## Not used by simulation

- ConversationRunner
- advisor_brain
- sales_advisor_decision_policy
- flow_router
- turn_resolver
- response_frame
- response_contract
- composer legacy

## Still imported elsewhere

These components remain in the repository and can still be fallback paths outside the simulation lab. Do not delete them yet.

## Can disable for tenants v2

For simulation-only and preview-only v2 tenants, visible response copy should come only from `TurnOutput.final_message`.

## Can delete in next PR

None. Deletion should wait for provider-backed simulation and shadow to pass.

## Do not delete yet

- ConversationRunner production fallback.
- Legacy composer and response helpers until migration is complete.
- Tooling that is still referenced by non-v2 routes.
"""


def _case_row(case: Any) -> str:
    main_failure = case.failure_reasons[0] if case.failure_reasons else ""
    return (
        f"| `{case.case_id}` | {case.category} | `{case.conversation_id}` | "
        f"{case.metadata.get('final_stage')} | `{case.score}` | {case.status} | "
        f"{_escape(main_failure)} | false |"
    )


def _transcript(case: Any, turns: list[Any]) -> str:
    selected = [turn for turn in turns if turn.case_id == case.id]
    lines = [
        f"### {case.case_id}",
        "",
        f"- conversation_id: `{case.conversation_id}`",
        f"- initial stage: `{case.metadata.get('initial_stage')}`",
        f"- final stage: `{case.metadata.get('final_stage')}`",
        f"- initial fields: `{case.metadata.get('initial_contact_fields')}`",
        f"- final fields: `{case.metadata.get('final_fields')}`",
    ]
    for turn in selected:
        lines.extend(
            [
                "",
                f"- customer message: {_escape(turn.customer_message)}",
                f"- agent final_message: {_escape(turn.actual_final_message)}",
                f"- citations: `{len(turn.citations)}`",
                f"- field updates: `{turn.field_updates}`",
                f"- lifecycle movements: `{turn.lifecycle_update}`",
                f"- actions: `{turn.actions}`",
                f"- policy: `{turn.policy_result}`",
                f"- confidence: `{turn.confidence}`",
                f"- expected vs actual: `{turn.expected_behavior}` / `{turn.pass_fail}`",
            ]
        )
    return "\n".join(lines)


def _counter_lines(counter: Counter) -> str:
    lines = [
        f"- `{key}`: `{value}`"
        for key, value in counter.items()
        if key
    ]
    return "\n".join(lines) or "- none"


def _escape(value: object) -> str:
    return str(value or "").replace("\n", " ").replace("|", "\\|")
