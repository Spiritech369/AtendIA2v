# Dinamo Next Codex Prompts

Generated: 2026-06-03

Purpose: ready-to-use prompts for future Codex passes. These prompts are not executed by this audit.

## 1. Prompt Diet

```text
Audit and reduce the Dinamo/Francisco prompt without changing runtime behavior yet.

Constraints:
- Do not hardcode Dinamo, motos, credit rules, tenant documents or commercial facts inside agent_runtime_v2.
- Keep legacy runner fallback untouched.
- Preserve TurnOutput.final_message as the only visible final copy authority.
- Tools/actions must return structured data, not final visible text.
- Make no production config changes.

Tasks:
1. Create a reduced prompt draft that keeps only role, tone, copy style, no-invention policy and tool-use obligations.
2. Remove plan mapping, prices, requirements, quote math, workflow triggers, field writes and lifecycle rules from prompt text.
3. For every removed rule, map the target owner: tool, StateWriter, guard, workflow, KB or eval.
4. Add focused tests that prove removed facts are not still prompt-owned.
5. Produce a report with before/after prompt sections and residual risks.
```

## 2. Tool Contract Audit

```text
Design and audit the mandatory deterministic tool contract for Dinamo/AtendIA.

Constraints:
- No production behavior changes unless tests and migration gates are included.
- Do not put tenant-specific commercial rules in agent_runtime_v2.
- Prefer tenant configuration and tenant-scoped data.
- Tools return structured data only.

Tasks:
1. Define contracts for catalog.retrieve, credit_plan.resolve, quote.resolve, requirements.retrieve, faq.retrieve and document.check.
2. Compare current tools against the target contracts.
3. Identify duplicate or conflicting current tool names.
4. Ensure every result includes tenant_id, evidence/source refs, confidence, ambiguity, and safe-to-persist metadata.
5. Add contract tests for wrong quote mode, wrong-plan docs, ambiguous model, por fuera, Buro, and document evidence.
6. Produce a migration plan that keeps legacy fallback intact.
```

## 3. State Writer Contract

```text
Audit and implement the StateWriter business-field contract for Dinamo/AtendIA with focused tests.

Constraints:
- Preserve tenant isolation.
- Do not accept direct LLM writes for business fields.
- No customer-facing copy outside TurnOutput.final_message.
- Keep legacy fallback until migration is evaluated.

Tasks:
1. Define canonical fields and aliases for Moto, Tipo_Compra, Cumple_Antiguedad, Plan_Credito, Plan_Enganche, Buro, Ubicacion_Interes, Cotizacion_Enviada, Ultima_Cotizacion, Docs_Checklist, Doc_Incompletos, Doc_Completos, Ultimo_Documento_Recibido, Pipeline, Handoff_Humano, Motivo_Handoff and Followup_Status.
2. Require trusted tool/action evidence for each accepted write.
3. Ensure quote snapshots invalidate on model, plan or mode change.
4. Ensure document lifecycle updates require attachment/checklist evidence.
5. Add tests for unsafe writes, stale quote, vague model, and docs-without-attachment.
6. Produce a report of rejected writes and accepted write metadata.
```

## 4. Workflow Trigger Contract

```text
Audit and implement deterministic business workflow triggers for Dinamo/AtendIA.

Constraints:
- Do not trigger critical sales workflows from keyword-only conditions.
- Preserve workflow idempotency and traceability.
- No production rollout without tests and canary gates.

Tasks:
1. Define events: lead_started, plan_identified, quote_sent, docs_requested, document_received, docs_incomplete, docs_complete, handoff_required, followup_1d, followup_3d, followup_7d and closed.
2. Define required payload, source evidence, trace id and idempotency key for each event.
3. Bind quote_sent to QuoteSafetyGuard, plan_identified to StateWriter accepted plan write, and docs_complete to checklist completion.
4. Add workflow validation/linting that blocks critical triggers based only on contains/keywords.
5. Add tests for duplicate prevention and stage moves without evidence.
6. Produce a workflow readiness report.
```

## 5. Human Sales Quality Eval

```text
Build a Dinamo human-sales quality eval suite for Francisco-style replies.

Constraints:
- Do not change production behavior in this pass.
- Evaluate final customer-visible copy only through TurnOutput.final_message or the current live equivalent.
- Facts must be checked against tool/state evidence, not prompt memory.

Tasks:
1. Create scenarios for credit vs cash, plan selection, ambiguous model, quote, post-quote ok/va/si, requirements, Buro, por fuera, uploads and handoff.
2. Score replies for correctness, no invention, one next step, human tone, no repetition, no internal terms, and evidence traceability.
3. Include negative tests for wrong-plan docs, stale quote, generic docs and false handoff.
4. Run against legacy and v2/shadow outputs if available.
5. Produce a ranked report with pass/fail, regressions and recommended blockers before canary.
```

## 6. Single Contact Smoke

```text
Run a single-contact Dinamo smoke test in the safest available mode.

Constraints:
- Start with send disabled or shadow/preview.
- Do not broaden rollout.
- Keep legacy fallback available.
- Do not modify tenant config unless explicitly requested.

Tasks:
1. Use one controlled contact/thread and run the full flow: greeting, seniority, plan, model, quote, post-quote acknowledgement, requirements, document upload simulation, docs incomplete/complete, handoff.
2. Capture turn traces, tool calls, StateWriter writes, workflow events, final messages and any side effects.
3. Verify no unsafe quote, no wrong-plan docs, no repeated qualification, no stale quote, no stage move without evidence and no duplicate workflow side effects.
4. Produce a smoke report with exact blocker list and go/no-go recommendation.
```
