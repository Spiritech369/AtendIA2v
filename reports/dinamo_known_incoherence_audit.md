# Dinamo Known Incoherence Audit

Generated: 2026-06-03

Scope: audit known answer/state/workflow incoherence risks. No runtime behavior was changed.

Final decision: MOST_INCOHERENCE_COMES_FROM_NON_UNIFORM_TOOL_AND_STATE_AUTHORITY

## Top Risks

| # | Incoherence | Current Mitigation | Residual Risk | Required Owner |
| --- | --- | --- | --- | --- |
| 1 | Customer asks credit but response quotes cash | Quote safety, quote policies, quote mode flags | Legacy/composer paths can still mix mode if quote evidence is not mandatory | `quote.resolve` + QuoteSafetyGuard |
| 2 | Generic documents after plan is known | `lookup_requirements`, checklist, requirements JSON | FAQ and prompt can answer generic requirements | `requirements.retrieve` |
| 3 | Bot asks for documents before quote | Prompt rules, sales advisor policy, doc guards | Legacy decision path can still route to docs early in edge cases | Runtime policy + requirements guard |
| 4 | Repeats seniority/income after already answered | Operational state, progress guard, memory policies | Mixed field aliases can hide prior answer | StateWriter + operational state aliases |
| 5 | Model/plan changes but old quote is reused | v2 StateWriter invalidates quote on product/plan change | Not universal in all live legacy paths | StateWriter + quote snapshot contract |
| 6 | "Por fuera" treated as not eligible | Plan resolver maps informal work to configured plan in some paths | Prompt/FAQ ambiguity could still reject incorrectly | `credit_plan.resolve` |
| 7 | Buró causes automatic rejection | Prompt/FAQ say flexible handling | If encoded as hard rule elsewhere, could over-reject | FAQ/tool policy + no hard reject guard |
| 8 | "ok/va/si" after quote restarts flow | Post-quote rules and acknowledgement policies | Ambiguous short replies need quote context | Conversation memory + StateWriter |
| 9 | "La primera/esa/la otra" model reference unresolved | Recent candidate policy exists | Candidate memory can be missing/stale | `catalog.retrieve` with candidate references |
| 10 | "Moto del anuncio" saved as actual model | Vague reference policy exists | Raw vague text can still be persisted if not blocked | StateWriter requires catalog evidence |
| 11 | False handoff from fallback text | v2 fallback marks low confidence/human need; reports show checks | Legacy fallback/handoff logic still distributed | Handoff policy + event reason enum |
| 12 | Pipeline moves to paperwork incomplete without attachment | v2 StateWriter and Dinamo bridge block doc stage without evidence | Any alternate stage updater can bypass if not contract-bound | Lifecycle + document.check evidence |
| 13 | Workflow fires from keyword instead of state | Workflow engine supports structured events | `contains` operator can be misused for business triggers | Workflow trigger contract |
| 14 | Tool result text becomes visible reply | v2 schemas reject visible text keys in tool/action results | Legacy tools/composers need consistent boundary | `TurnOutput.final_message` only |

## Required Incoherence Detail Matrix

| Incoherence | Possible Responsible File | Responsible Layer | Severity | How To Reproduce | Recommended Test | Recommended Fix | Requires Runtime Change Or Config/Prompt |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Credit lead receives cash quote | `tools/quote.py`, `quote_safety.py`, `sales_advisor_decision_policy.py`, `dinamo_agent_runtime.py` | Quote Resolver / Guard | HIGH | User says "quiero credito" then asks "cuanto queda la X" | Assert quote mode is credit or asks plan info; no cash-only quote | Make `quote.resolve` mode mandatory and require snapshot before visible price | Runtime/tool contract |
| Generic documents when plan exists | `lookup_requirements.py`, `FAQ_DINAMO.json`, `Prompt Agente IA.txt` | Requirements Resolver / KB routing | HIGH | Resolve plan 5, then ask "que documentos necesito" | Assert only plan 5 docs are returned | Route docs questions to `requirements.retrieve`; FAQ refuses owned topics | Tool config/runtime routing |
| Documents requested before quote | `advisor_brain_prompt.py`, `sales_advisor_decision_policy.py`, `dinamo_agent_runtime.py` | Francisco Agent / Policy | HIGH | User passes seniority and gives plan but no model/quote | Assert bot asks model/quote path, not docs | Add policy guard: docs request requires valid quote or explicit doc question/upload | Runtime policy |
| Repeats seniority already saved | `operational_state.py`, `conversation_progress.py`, `state_write_policy.py` | Intent/State Extractor | MEDIUM | Save seniority true, next turn asks same question | Assert next step advances to plan/model | Canonical aliases plus progress guard memory | Runtime/state contract |
| Repeats income/plan already saved | `operational_state.py`, `credit_plan_invariants.py`, `dinamo_agent_runtime.py` | Credit Plan Resolver / State | MEDIUM | Save plan, then ask quote | Assert no repeated income question | Accept plan evidence once and use StateWriter aliases | Runtime/state contract |
| Model changes without quote invalidation | `state_writer.py`, `quote_memory_policy.py`, legacy state policy | State Writer / Quote | HIGH | Quote model A, then user changes to model B | Assert previous quote invalidated and new quote required | StateWriter invalidation must cover all live paths | Runtime/state contract |
| "Por fuera" treated as not eligible | `credit_plan_invariants.py`, prompt/FAQ text | Credit Plan Resolver | MEDIUM | User says "trabajo por fuera/sin comprobantes" | Assert plan resolves to configured informal/no-comprobante path if eligible | Tool-owned alias mapping with no auto reject | Tool config |
| Buro automatic rejection | `FAQ_DINAMO.json`, prompt/FAQ logic | FAQ / Guard | MEDIUM | User asks "si tengo buro puedo?" | Assert no hard disqualification; asks/answers policy safely | FAQ policy and no-hard-reject eval | KB/tool config |
| "ok/va/si" after quote does not advance | `acknowledgement_policy.py`, `advisor_brain_prompt.py`, memory policies | Conversation Progress | MEDIUM | Send quote, then user replies "va" | Assert soft close or docs next step, not reset | Bind short acknowledgement to last quote context | Runtime/policy |
| "La primera/esa/la otra" not resolved | `catalog_reference_policy.py`, `dinamo_agent_runtime.py` | Catalog Resolver | MEDIUM | Show candidates, user says "la primera" | Assert selected candidate or clarification if memory missing | Make candidate references part of `catalog.retrieve` state | Runtime/tool contract |
| "Moto del anuncio" saved as model | `catalog_reference_policy.py`, StateWriter, bridge state writes | Catalog Resolver / State Writer | HIGH | User says "quiero la moto del anuncio" | Assert no `Moto` write without canonical catalog match | StateWriter requires catalog evidence | Runtime/state contract |
| False handoff by fallback | `advisor_pipeline.py`, `handoff_helper.py`, `ConversationRunner` fallback | Handoff / Guard | MEDIUM | Provider fails or ambiguous message | Assert handoff requires reason enum or policy threshold | Handoff event contract with explicit reason | Runtime/workflow contract |
| Paperwork incomplete without attachment | `state_writer.py`, `pipeline_evaluator.py`, `dinamo_agent_runtime.py` | Document Checker / Lifecycle | HIGH | User says "ya mande papeles" with no attachment | Assert no document accepted and no paperwork stage move | `document.check` evidence required for doc lifecycle | Runtime/state/workflow contract |
| Workflow keyword trigger | `workflows/engine.py`, workflow definitions | Workflow Engine | HIGH | Configure critical stage move using `contains` on message text | Assert lint blocks or marks dangerous for live | Block keyword-only critical business triggers | Runtime/workflow validation |

## Evidence-Based Observations

1. Runtime v2 contains the right visible-copy boundary: `TurnOutput.final_message`.
2. Runtime v2 has strong structured-result enforcement for tools/actions.
3. Quote safety exists and should be the gate for all visible price/quote text.
4. StateWriter already knows how to block stale quote writes and doc lifecycle changes without evidence.
5. Requirements are tenant/pipeline scoped, but prompt/FAQ overlap can still answer with generic docs.
6. Workflows are technically robust, but business trigger names need a deterministic contract.
7. Legacy runner remains the live path in important flows, so any target guarantee must either wrap legacy or be canary-gated through v2.

## Tests Needed

| Test | Expected Result |
| --- | --- |
| User says "quiero credito" then asks price | No cash quote unless cash intent is explicit |
| User picks plan 5 then asks docs | Only plan 5 requirements are requested |
| User says "ok" after quote | Bot soft-closes or requests next step; does not restart qualification |
| User changes model after quote | Previous quote snapshot is invalidated |
| User says "por fuera" | Bot resolves informal/self-employed path if configured; does not reject automatically |
| User asks about Buro | Bot answers flexible policy; no automatic disqualification |
| User says "la primera" after catalog candidates | Bot resolves the first candidate or asks for clarification if candidate memory missing |
| User uploads no attachment but says "ya mande papeles" | No document accepted/stage move without evidence |
| Workflow with keyword "docs" configured for stage move | Business-critical stage move is blocked or linted |
| Tool returns a `message` field | Runtime rejects it as customer-visible text authority |

## Audit Conclusion

The remaining incoherences are not random answer-quality issues. They are architecture authority issues: facts must come from tools, writes from StateWriter, side effects from workflows, and final copy from `TurnOutput.final_message`.
