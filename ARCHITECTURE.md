# ARCHITECTURE.md

## Stable Overview

AtendIA is a tenant-aware platform for conversational operations: inbox, AI
agents, Knowledge OS, contact memory, lifecycle/pipeline state, tools, actions,
workflows, evaluation, tracing, and safe channel delivery.

This file is the stable high-level summary. The canonical Product-First
transformation lives in `Arquitectura-Deseada.md`. Operational rules for Codex
live in `AGENTS.md`. Current technical contracts live in `docs/architecture/`.

Core principle:

**ChatGPT converses and reasons. AtendIA governs validation, state, actions,
publication, safety, auditability, and sending.**

## Product Surfaces

- Inbox: operator view of conversations, messages, assignment, and handoff.
- Agent Builder: tenant-configured AI behavior, voice, tools, fields,
  workflows, policy, deployment, and rollback.
- Knowledge Sources: tenant-scoped catalog, FAQ, requirements, documents,
  policies, and other factual sources.
- Contact Memory: validated contact fields, conversation memory, documents, and
  lifecycle context.
- Lifecycle/Pipeline: tenant-defined stages, statuses, and measurable progress.
- Action Registry: structured, permissioned, auditable read/write capabilities.
- Workflows: tenant-scoped automations gated by policy and side-effect flags.
- Test Lab: DB-backed no-send testing before publish or live activation.
- Publish Control: explicit state machine from draft to test, approval,
  published, paused, and rollback.
- Trace/Analytics: why the assistant responded, which tools ran, what was
  written, what was blocked, and what would be sent.

## Runtime Flow

One customer turn should follow one DB-backed runtime path:

1. Channel adapter receives the inbound message.
2. Inbound persistence stores message, attachments, and conversation linkage.
3. Deployment Resolver selects the active published agent version.
4. AgentService builds the turn through ContextBuilder.
5. ChatGPT/Semantic Provider interprets intent and proposes structured work.
6. Tenant-aware tools resolve hard facts such as catalog, quote, requirements,
   FAQ, documents, or integrations.
7. StateWriter writes only validated, evidenced state.
8. Composer produces one `TurnOutput.final_message`.
9. Policy validates visible copy, tool usage, risk, side effects, and fallback
   safety.
10. SendAdapter applies no-send or live send policy.
11. Universal turn trace records context, tools, decisions, writes, blocks,
    final output, and send decision.

No-send and live-candidate must use the same context, tools, StateWriter,
Policy, Composer, and TurnOutput. The only intended difference is SendAdapter
behavior.

## Runtime Authorities

- Conversational interpretation: ChatGPT/Semantic Provider.
- Business facts: tenant-scoped data and Knowledge OS sources.
- Tool results: structured tool/action payloads.
- Field writes: StateWriter with evidence and tenant policy.
- Customer-facing copy: `TurnOutput.final_message`.
- Send/no-send decision: SendAdapter and runtime send policy.
- Debug truth: universal turn trace and audit metadata.

If a required tool is missing, skipped, failed, or blocked, the turn must fail
closed for visible sending. If policy validation fails, the turn must fail
closed for visible sending.

## Tenant Isolation

Runtime code may know generic concepts such as tenant, contact, message, field,
tool, policy, lifecycle, action, deployment, and trace. It must not know a
tenant's products, prices, credit plans, document rules, vertical vocabulary, or
workflow policy unless those are loaded from tenant-scoped configuration,
domain contracts, Knowledge OS, or published tenant data.

## Live Safety

Live traffic is not a separate brain. It is the same DB-backed runtime path with
send enabled.

Before live activation:

- The relevant Product-First phase must satisfy Definition of Ready.
- DB-backed Test Lab must pass with the real tenant, contact, conversation,
  knowledge sources, tools, StateWriter, Policy, and final message.
- Outbox, workflow side effects, actions, canary, and production scope must be
  explicitly gated.
- The exact final message that would be sent must be reviewed.
- Rollback must be documented and immediately available.

Fixtures, mocks, local-only sources, or alternate harnesses can support unit
tests, but they do not prove live readiness.

## Legacy And Migration

Legacy runner behavior remains only as temporary migration support until Runtime
V2/Product-First AgentService is fully migrated, evaluated, and explicitly
approved for removal. Legacy must not replace visible output for published
Runtime V2 agents.

The target is one AgentService boundary for DB-backed no-send and live-candidate
execution, with legacy classified as KEEP, MERGE, DEGRADE, BLOCK_FOR_V2,
DELETE_LATER, or UNKNOWN_NEEDS_AUDIT.

## Specs And Reports

- `Arquitectura-Deseada.md` wins for Product-First transformation direction.
- `docs/architecture/` contains current contracts and decisions.
- `docs/runbooks/` contains operational procedures.
- `reports/` contains historical evidence, incident analysis, audits, and
  temporary findings.
