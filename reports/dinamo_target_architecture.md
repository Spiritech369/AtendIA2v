# Dinamo Target Architecture

Generated: 2026-06-03

Scope: proposed target architecture for tenant-neutral AtendIA/Dinamo runtime. No implementation changes were made.

Final decision: TARGET_IS_VALID_AFTER_TOOL_CONTRACT_FIRST_MIGRATION

## Target Principle

The AI should sell like Francisco, but it should not own commercial truth. The runtime owns truth through tools, StateWriter, guards, workflows and traces.

## Target Flow

```text
Inbound message / attachment
  -> normalized turn context
  -> Francisco Agent
       understands intent
       proposes next step
       requests tools
  -> Mandatory deterministic tool router
       catalog.retrieve
       credit_plan.resolve
       quote.resolve
       requirements.retrieve
       faq.retrieve
       document.check
  -> StateWriter
       accepts/rejects field writes
       invalidates stale quote data
       requires evidence for docs/stage changes
  -> Composer
       writes customer-facing copy only from structured evidence
  -> TurnOutput.final_message
       one visible response authority
  -> Guards
       quote safety
       progress/repetition safety
       policy and tenant isolation safety
  -> Workflow engine / lifecycle / actions
       deterministic events
       idempotent side effects
       handoff/followups/stage updates/outbox
  -> Trace and why-answer
```

## Responsibilities By Layer

| Layer | Responsibility | Deterministic Or AI |
| --- | --- | --- |
| Francisco Agent | Converses, understands intent, chooses next step and asks for tools | AI with strict contract |
| Intent/State Extractor | Detects intent and proposes state changes with evidence | AI proposal plus deterministic validation |
| Catalog Resolver | Resolves canonical model, aliases, candidates, prices/plans/ficha source facts | Deterministic tool/retrieval |
| Credit Plan Resolver | Converts income/work type into plan and enganche | Deterministic tenant data/config |
| Quote Resolver | Generates quote snapshot with product, mode, plan, payment and term | Deterministic tool |
| Requirements Resolver | Returns documents by selected plan and missing docs | Deterministic tool |
| FAQ Resolver | Answers general FAQ and objections with citations | Retrieval tool with routing guard |
| Document Checker | Validates real uploaded documents and checklist deltas | Deterministic/vision-assisted tool with evidence |
| StateWriter | Accepts/rejects writes and invalidates stale quote state | Deterministic policy |
| Composer | Produces human final copy only from structured evidence | AI copy layer |
| Guards | Block unsafe visible copy, repetition, stale quote and unsafe side effects | Deterministic policy |
| Workflow Engine | Emits and executes business events, followups, handoff, stage moves | Deterministic engine |
| Observability | Traces why an answer/action happened | Deterministic audit layer |

## AI Responsibilities

The AI may:

- classify the user's conversational intent
- decide whether more information is needed
- select which deterministic tool is required
- draft natural customer-facing copy from structured evidence
- explain ambiguity in a human way
- recommend handoff with a structured reason

The AI must not:

- invent prices, payments, down payments, model availability, requirements or branch policies
- save contact fields directly
- decide a pipeline stage directly
- mark documents complete/incomplete without evidence
- trigger workflows directly
- produce customer-facing text from tool/action payloads
- hardcode Dinamo rules inside `agent_runtime_v2`

## Deterministic Responsibilities

Deterministic layers own:

- catalog identity and model ambiguity
- credit plan and enganche mapping
- quote snapshots and stale quote invalidation
- requirements and missing documents
- document accepted/rejected/complete state
- accepted customer fields
- workflow trigger payloads
- side-effect idempotency
- audit traces and why-answer evidence

## Mandatory Tools

| Tool Contract | Purpose | Required Output |
| --- | --- | --- |
| `catalog.retrieve` | Resolve catalog model, aliases, candidates and ambiguity | canonical model, candidates, confidence, source refs |
| `credit_plan.resolve` | Resolve credit plan, down payment percent and eligibility state | plan code/name, enganche, evidence, missing inputs |
| `quote.resolve` | Produce cash/credit quote snapshot | product, mode, price, enganche, payment, term, plan, snapshot id |
| `requirements.retrieve` | Return plan-scoped requirements and missing docs | required, received, rejected, missing, complete |
| `faq.retrieve` | Answer general FAQ/objections only | answer, citations, category, refusal/redirect if deterministic tool owns topic |
| `document.check` | Classify uploaded documents and reconcile checklist | document type, accepted/rejected, reason, checklist delta |

## StateWriter Ownership

StateWriter owns all accepted customer/business state:

- customer fields
- quote snapshot and quote sent status
- document checklist state
- document complete/incomplete flags
- pipeline/lifecycle proposals
- handoff flags/reasons
- followup state

StateWriter may accept a write only when the write includes structured evidence from a trusted source.

## Workflow Ownership

Workflow/lifecycle owns:

- `lead_started`
- `plan_identified`
- `quote_sent`
- `docs_requested`
- `document_received`
- `docs_incomplete`
- `docs_complete`
- `handoff_required`
- followup events
- close events
- stage moves
- bot pause/resume
- outbox/action side effects

## Guards Must Block

- price or payment text without trusted `quote.resolve` evidence
- quote text with stale product, plan or mode
- cash quote when the accepted user intent is credit
- repeated seniority/income/model questions when state is already accepted
- handoff without structured reason
- document lifecycle updates without uploaded document/checklist evidence
- duplicate side effects or non-idempotent workflow actions
- tool/action payloads attempting to become customer-visible final copy

## Prompt Ownership

The prompt should contain only:

- role and tone
- copy style
- behavioral constraints
- tool-use obligation
- no-invention policy
- final-message boundary

Everything else belongs to tenant data, tools, StateWriter, guards, workflows or evals.

## Evaluation Gate

Before any broader production rollout:

1. Contract tests for each mandatory tool.
2. StateWriter tests for every business field.
3. Workflow trigger tests for every target event.
4. Prompt diet evals against known incoherence cases.
5. Single-contact smoke in shadow/send-disabled mode.
6. Canary with legacy fallback and rollback plan.

## Target Acceptance Statement

At target, a Dinamo answer is valid only when every customer-facing fact can be traced to a tool result, accepted state, tenant configuration, or cited KB source, and every side effect can be traced to a deterministic event/action.
