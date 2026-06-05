# Dinamo Prompt Audit

Generated: 2026-06-03

Scope: audit prompt/business logic placement. No prompt was changed.

Final decision: PROMPT_MUST_BE_REDUCED_AFTER_TOOL_CONTRACTS

## Files Reviewed

- `docs/Prompt Agente IA.txt`
- `core/atendia/runner/advisor_brain_prompt.py`
- `core/atendia/runner/agent_final_response.py`
- `core/atendia/runner/composer_prompts.py`
- `core/atendia/runner/response_frame.py`

## High-Level Finding

The Dinamo prompt contains useful sales behavior, but it also carries rules that should be deterministic: plan mapping, down payment percentages, quote eligibility, quote format facts, document requirements, field writes, escalation triggers, and flow transitions.

This makes the assistant fragile because prompt text can drift from catalog, requirements, pipeline rules, workflow triggers, and state writer policy.

## What Should Stay In The Prompt

| Prompt Responsibility | Keep? | Notes |
| --- | --- | --- |
| Identity as Francisco, human sales advisor tone | KEEP | This is copy/behavior, not business data |
| Natural, concise, WhatsApp-style response | KEEP | Composer may enforce this too |
| One clear next question when needed | KEEP_WITH_GUARD | Prompt can express it, guard should enforce repetition/progress |
| Do not expose internal names, JSON, tool names, or backend logic | KEEP | Also belongs in response contract |
| Do not invent prices, requirements, documents or policies | KEEP_WITH_GUARD | Prompt reminds; tools/guards enforce |
| Ask only for missing information needed for the current step | KEEP_WITH_STATE | Requires operational state and tool evidence |

## What Must Leave The Prompt

| Rule/Behavior | Current Location | Target Owner | Reason |
| --- | --- | --- | --- |
| Plan menu and down payment mapping 1-6 | `docs/Prompt Agente IA.txt`, `advisor_brain_prompt.py`, `credit_plan_invariants.py` | `credit_plan.resolve` from tenant config/data | Tenant-specific commercial rules cannot live in prompt or global core constants |
| Catalog/model resolution and max candidates | Prompt plus catalog resolver logic | `catalog.retrieve` | Model identity must be canonical and cited |
| Price, down payment amount, payment amount, term | Prompt quote section | `quote.resolve` plus `QuoteSafetyGuard` | Visible price must match structured quote snapshot |
| Whether quote is cash or credit | Prompt flow rules and legacy policy | `quote.resolve`, StateWriter, quote guard | Prevents cash/credit mixing |
| Document requirement list | Prompt and FAQ | `requirements.retrieve` and document checklist | Prevents generic or wrong-plan documents |
| Whether docs are complete/incomplete | Prompt stage rules | `document.check`, checklist, StateWriter, pipeline evaluator | Requires attachment/checklist evidence |
| Field write instructions like "guardar contact.X" | Prompt source file | StateWriter | LLM may propose, but StateWriter must be authority |
| Pipeline stage changes | Prompt flow and legacy runner | Lifecycle service / workflow engine | Stage must be deterministic and auditable |
| Handoff triggers | Prompt escalation section | Handoff policy/workflow events | Avoid false handoff from phrasing/fallback |
| Followup timing | Prompt or composer behavior | Workflow/followup scheduler | Time-based actions must be deterministic |

## Required Rule Classification

| Rule Or Instruction Found | Classification | Target Owner / Action |
| --- | --- | --- |
| Francisco identity, informal sales tone, human advisor style | `KEEP_IN_PROMPT` | Prompt/composer behavior |
| One clear customer question per turn | `KEEP_IN_PROMPT` | Prompt plus ConversationProgressGuard |
| Do not expose internal JSON/tool/backend terms | `KEEP_IN_PROMPT` | Prompt plus response contract |
| Do not invent prices, requirements or catalog facts | `KEEP_IN_PROMPT` | Prompt reminder; guards enforce |
| Plan option 1-6 mapping and enganche percentages | `MOVE_TO_TOOL` | `credit_plan.resolve` from tenant-scoped data/config |
| Model alias/category/price/ficha resolution | `MOVE_TO_TOOL` | `catalog.retrieve` |
| Quote price, down payment, payment and term formatting facts | `MOVE_TO_TOOL` | `quote.resolve` and QuoteSafetyGuard |
| Credit/cash mode decision for quote | `MOVE_TO_TOOL` | `quote.resolve` with explicit mode |
| Document requirements by plan | `MOVE_TO_TOOL` | `requirements.retrieve` |
| FAQ answers for Buro, objections, hours, general policy | `MOVE_TO_KB` | `faq.retrieve` with citations and routing limits |
| "Guardar contact.X" field instructions | `MOVE_TO_STATE_WRITER` | StateWriter accepted updates only |
| Invalidate old quote when model/plan changes | `MOVE_TO_STATE_WRITER` | StateWriter invalidation rule |
| Move to paperwork/document stages | `MOVE_TO_WORKFLOW_ENGINE` | Lifecycle/workflow event after document evidence |
| Followup timing and side effects | `MOVE_TO_WORKFLOW_ENGINE` | Followup/workflow scheduler |
| Block unsafe price, stale quote and repetition | `MOVE_TO_GUARD` | QuoteSafetyGuard and ConversationProgressGuard |
| Prompt-driven requirement list when requirements KB/tool exists | `DELETE_CONFLICTING_RULE` | Delete from prompt; requirements tool owns |
| Prompt-driven plan/down-payment constants duplicated in code/data | `DELETE_CONFLICTING_RULE` | Delete from prompt after tool contract exists |

## Prompt Conflicts And Ambiguities

1. The source prompt says the assistant can decide flow priority, while the target architecture requires tools/state/workflows to own decisions.
2. It includes exact plan/down payment mappings that already exist in code/data, creating drift risk.
3. It includes document requirements while `Requisitos_Credito_Dinamo.json` says requirements should be resolved from file, not prompt.
4. FAQ content overlaps with credit requirements and down payment rules; the prompt must not let FAQ override deterministic tools.
5. It asks the agent to save contact fields, but the target architecture says StateWriter is the only authority for accepted writes.
6. It mixes post-quote acknowledgements, document requests and handoff logic in copy rules instead of structured events.

## Recommended Prompt Diet

The future prompt should be short and generic:

```text
You are Francisco, a human sales advisor for the tenant.
Use only structured tool results and current state.
Never invent prices, plans, requirements, catalog facts or document status.
If required evidence is missing, ask one concise question.
Write only the customer-facing final copy.
Do not perform side effects or claim that a field/stage/document was updated unless the runtime evidence says so.
```

Tenant-specific facts must be supplied through tenant configuration, tenant data, and tool results.

## Required Tests After Prompt Diet

1. Quote cannot mention price without `quote.resolve`.
2. Requirements cannot be answered from FAQ when plan is known.
3. Plan/down payment cannot be copied from prompt constants.
4. Customer field writes are proposed only, then filtered by StateWriter.
5. Post-quote "ok/va/si" does not restart seniority or income.
6. Prompt cannot trigger handoff or workflow directly.
