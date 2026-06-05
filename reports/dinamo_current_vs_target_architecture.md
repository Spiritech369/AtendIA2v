# Dinamo Current vs Target Architecture

Generated: 2026-06-03

Scope: compare current implementation against the desired deterministic Dinamo/AtendIA architecture.

Final decision: ARCHITECTURE_NEEDS_TOOL_CONTRACT_FIRST

## Status Legend

Only the statuses requested by the audit brief are used:

- `EXISTS_GOOD`
- `EXISTS_PARTIAL`
- `EXISTS_BUT_PROMPT_HEAVY`
- `EXISTS_BUT_HARDCODED`
- `MISSING`
- `AMBIGUOUS`
- `DANGEROUS_FOR_LIVE`

## Required Current vs Target Table

| Capa objetivo | Existe hoy | Archivo/clase actual | Estado | Brecha | Riesgo |
| ------------- | ---------- | -------------------- | ------ | ------ | ------ |
| Francisco Agent | Yes | `advisor_brain_prompt.py`, `advisor_brain.py`, `agent_final_response.py`, `composer_*` | `EXISTS_BUT_PROMPT_HEAVY` | Prompt and bridge still decide sales flow, documents and quote-related copy | Incoherent replies when prompt memory conflicts with tool/state evidence |
| Intent/State Extractor | Yes | `OperationalStateReconciler`, NLU/provider code, `state_write_policy.py`, advisor brain outputs | `EXISTS_PARTIAL` | Multiple sources infer state and field names are mixed | Repeated questions or writes to the wrong field alias |
| Catalog Resolver | Yes | `search_catalog.py`, `deterministic.list_catalog`, commercial catalog service, Dinamo KB helper | `EXISTS_PARTIAL` | No single mandatory `catalog.retrieve` contract across all paths | Vague model references can become unsafe state or wrong quote |
| Credit Plan Resolver | Yes | `deterministic.resolve_credit_plan`, `credit_plan_invariants.py`, pipeline selection catalog | `EXISTS_BUT_HARDCODED` | Dinamo plan order, aliases and down payments are hardcoded globally in core | Tenant leakage, stale commercial rules, hard-to-audit plan decisions |
| Quote Resolver | Yes | `tools/quote.py`, quote memory policies, `QuoteSafetyGuard` | `EXISTS_PARTIAL` | Quote contract name/result authority is not uniform (`quote` vs `quote.resolve` semantics) | Cash/credit mixing or stale quote in legacy paths |
| Requirements Resolver | Yes | `lookup_requirements.py`, `getMissingDocuments`, `DocumentChecklist` | `EXISTS_GOOD` | Must still be made mandatory over FAQ/prompt when plan is known | Generic documents if FAQ/prompt answers first |
| FAQ Resolver | Yes | `lookup_faq.py`, FAQ source docs, Knowledge OS | `EXISTS_PARTIAL` | FAQ overlaps with plan/down-payment/requirements facts | FAQ may override deterministic tools |
| Document Checker | Partial | `vision.py`, attachment policies, `DocumentChecklist`, StateWriter doc evidence checks | `EXISTS_PARTIAL` | No single mandatory `document.check` contract owns accepted/rejected docs | Stage moves or docs-complete claims without evidence |
| State Writer | Yes | `DeterministicStateWriter`, legacy `state_write_policy.py` | `EXISTS_PARTIAL` | v2 StateWriter is strong, but live/legacy path still uses bridge policies and aliases | Unsafe writes if an alternate path bypasses v2 policy |
| Workflow Engine | Yes | `workflows/engine.py`, `workflow_events.py`, `pipeline_evaluator.py` | `EXISTS_PARTIAL` | Engine exists, but target business trigger names are not fully standardized | Keyword-style workflows or duplicate/early side effects |
| Guards | Yes | `QuoteSafetyGuard`, `ConversationProgressGuard`, response contract, sales advisor policies | `EXISTS_PARTIAL` | Guard coverage is strong in v2 but distributed in legacy | Unsafe visible text if not routed through v2 guard layer |
| Provider Reliability | Yes | `ProviderReliabilityLayer`, rollout/shadow/pilot policies | `EXISTS_GOOD` | Needs continued metrics during migration | Provider failures can still cause fallback-quality issues if not monitored |
| Eval Harness | Yes | `eval_lab/`, `simulation/`, provider batteries, `core/tests/agent_runtime/` | `EXISTS_GOOD` | Needs target-contract evals for the new architecture | Passing old evals may not prove tool/state/workflow authority |
| Observability | Yes | turn traces, workflow/action logs, `why_answer.py` | `EXISTS_GOOD` | Ensure every new contract emits evidence IDs and trace metadata | Good answer may be hard to audit if tool evidence is missing |
| Rollback | Yes | legacy runner, shadow mode, rollout policy, live-limited gates | `EXISTS_GOOD` | Must remain until parity/canary are proven | Premature cutover would be dangerous for live sales |

## Current Architecture Snapshot

```text
WhatsApp webhook
  -> message persistence and workflow event
  -> inbound burst debounce
  -> ConversationRunner live path
  -> Dinamo agent-first bridge or legacy composer
  -> tools/state/composer/handoff/outbox
  -> runtime v2 shadow path
```

## Target Architecture Snapshot

```text
WhatsApp webhook
  -> normalized inbound turn
  -> Francisco Agent proposes intent and next step
  -> mandatory deterministic tools
       catalog.retrieve
       credit_plan.resolve
       quote.resolve
       requirements.retrieve
       faq.retrieve
       document.check
  -> StateWriter validates all contact/pipeline writes
  -> Composer writes only from structured evidence
  -> TurnOutput.final_message
  -> guards validate visible copy
  -> deterministic workflow events and side effects
```

## Most Important Delta

The system has many correct pieces, but they are not yet governed by one mandatory tool contract. Because tool contracts are inconsistent, prompt and legacy bridge code still compensate by carrying business rules. That is the root cause of most remaining incoherence risks.

## Migration Implication

Do not start by rewriting the prompt again. First define and enforce the tool contracts, then reduce prompt authority, then bind StateWriter/workflow triggers to the structured tool outputs.
