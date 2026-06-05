# Dinamo Workflow Trigger Audit

Generated: 2026-06-03

Scope: audit workflow trigger coverage and deterministic event needs. No workflow definitions were changed.

Final decision: WORKFLOW_ENGINE_EXISTS_BUT_BUSINESS_TRIGGER_CONTRACT_IS_PARTIAL

## High-Level Finding

The workflow engine is robust: it validates definitions, limits recursion, records action runs idempotently, supports safe actions, and can evaluate structured events. The gap is not engine capability. The gap is the business event contract: Dinamo target events such as `plan_identified`, `quote_sent`, `docs_requested`, and `docs_complete` are not all standardized as first-class deterministic events across the live path.

## Existing Workflow Strengths

1. Trigger type allowlist.
2. Condition validation and reference validation.
3. Idempotent action recording to avoid duplicate side effects.
4. Self-trigger prevention.
5. Safe action types such as update field, move stage, assign, pause bot, notify, trigger workflow.
6. Agent runtime event bridge for turn completed, low confidence, human needed, lifecycle proposed, action executed, and risk flagged.
7. Pipeline evaluator supports rule-based stage selection and document-complete checks.

## Target Trigger Map

| Target Trigger | Current Equivalent | Status | Required Authority |
| --- | --- | --- | --- |
| `lead_started` | `message_received`, possible conversation-created flow | PARTIAL | Inbound persistence/conversation creation |
| `plan_identified` | `field_updated` on plan fields, agent lifecycle proposed | MISSING_CONTRACT | `credit_plan.resolve` plus StateWriter accepted update |
| `quote_sent` | `quote_sent` field/safety flag, message sent | PARTIAL | `quote.resolve` plus QuoteSafetyGuard accepted visible copy |
| `docs_requested` | Composer/doc request text, possible action/event | MISSING_CONTRACT | Requirements resolver result plus final response intent |
| `document_received` | `document_uploaded`, attachment/vision flows | PARTIAL | Attachment ingestion and `document.check` |
| `docs_incomplete` | checklist missing/rejected, stage update | PARTIAL | Document checklist result |
| `docs_complete` | `docs_complete_for_plan`, stage rules | EXISTS_PARTIAL | Document checklist all accepted for selected plan |
| `handoff_required` | `human_handoff_requested`, `agent_needs_human` | EXISTS_PARTIAL | Structured handoff reason/risk/low-confidence |
| `followup_1d` | followup scheduler/delay workflow | PARTIAL | Deterministic schedule created from state/event |
| `followup_3d` | followup scheduler/delay workflow | PARTIAL | Deterministic schedule created from state/event |
| `followup_7d` | followup scheduler/delay workflow | PARTIAL | Deterministic schedule created from state/event |
| `closed` | `conversation_closed` | EXISTS_PARTIAL | Close conversation action/event |

## Required Workflow Safety Matrix

| Trigger | Structured Condition | Required Field/Event | Evidence | Side Effect Idempotent? | Rollback / Safe Failure |
| --- | --- | --- | --- | --- | --- |
| `lead_started` | New conversation or first inbound event | `message_received` / conversation created | inbound message id | Required | If workflow fails, keep message persisted and retry/evaluate later |
| `plan_identified` | StateWriter accepted plan update | `Plan_Credito`, `Plan_Enganche` | `credit_plan.resolve` result | Required | If unsafe, reject write and do not fire trigger |
| `quote_sent` | Quote guard accepted visible quote | `Cotizacion_Enviada=true` | `quote.resolve` snapshot + final message trace | Required | If stale/unsafe, block quote_sent and rewrite/ask clarification |
| `docs_requested` | Final response requests missing plan docs | `Docs_Checklist.missing` | `requirements.retrieve` result | Required | If no plan/evidence, ask for missing plan info instead |
| `document_received` | Attachment ingested | attachment/document event | uploaded file/photo id | Required | If checker fails, preserve attachment and ask retry/handoff as policy |
| `docs_incomplete` | Checklist has missing/rejected required docs | `Doc_Incompletos` | `document.check` + checklist delta | Required | Do not move stage without evidence |
| `docs_complete` | All required docs accepted for selected plan | `Doc_Completos=true` | checklist complete for plan | Required | If plan changes, recompute and invalidate completion if needed |
| `handoff_required` | Structured reason emitted | `Handoff_Humano=true`, `Motivo_Handoff` | risk/low-confidence/human request enum | Required | If reason missing, do not create handoff |
| `followup_1d` | Eligible quote/docs state and no human takeover | `Followup_Status` schedule | accepted state + schedule id | Required | Use idempotency key per conversation/event/window |
| `followup_3d` | Eligible quote/docs state and prior followup state | `Followup_Status` schedule | accepted state + schedule id | Required | Use idempotency key per conversation/event/window |
| `followup_7d` | Eligible stale lead state and no close/handoff | `Followup_Status` schedule | accepted state + schedule id | Required | Cancel or skip if conversation closed/handoff |
| `closed` | Explicit close action or terminal stage | `conversation_closed` | close action/event id | Required | If close action fails, preserve state and retry idempotently |

## Triggers That Must Be Deterministic

The following must never be triggered only by keyword matching or prompt text:

- `plan_identified`
- `quote_sent`
- `docs_requested`
- `document_received`
- `docs_incomplete`
- `docs_complete`
- `handoff_required`
- followup scheduling
- pipeline stage moves
- bot pause/resume
- close conversation

## Keyword Trigger Risk

The workflow condition model supports operators such as `contains`. That is useful for generic automations, but risky for business-critical Dinamo sales stages. For quote/docs/handoff/stage movement, workflows should use structured fields/events from StateWriter, tool results, or lifecycle service only.

## Recommended Event Contract

Every target business event should include:

- `event_type`
- `tenant_id`
- `conversation_id`
- `contact_id`
- `trace_id`
- `source_turn_id`
- `source_tool`
- `source_evidence_id`
- `accepted_state_updates`
- `payload`
- `idempotency_key`

## Acceptance Criteria

1. `quote_sent` can fire only after quote visible copy passed QuoteSafetyGuard.
2. `docs_complete` can fire only after document checklist says all required docs for selected plan are accepted.
3. `plan_identified` can fire only after `credit_plan.resolve` result is accepted by StateWriter.
4. `docs_requested` can fire only when the final copy asks for plan-scoped missing docs from `requirements.retrieve`.
5. `handoff_required` must include an explicit reason enum.
6. All side effects have idempotency keys and traces.

## Audit Conclusion

Keep the workflow engine. Do not rebuild it. Add a Dinamo/tenant-neutral business trigger contract on top of structured runtime evidence.
