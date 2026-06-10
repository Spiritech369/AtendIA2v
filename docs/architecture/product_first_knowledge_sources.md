# Product-First Knowledge Sources

Date: 2026-06-06  
Status: Active architecture contract  
Canonical source: `Arquitectura-Deseada.md`

## Purpose

Knowledge Sources must become tenant-scoped product entities, not prompt text,
fixture files, or runtime shortcuts.

This document defines the target contract for source readiness, source health,
agent bindings, retrieval preview, publish blockers, and trace requirements.
It is documentation-only for this phase. It does not change runtime, DB,
WhatsApp, outbox, actions, workflows, smoke, or live flags.

## Product Principle

ChatGPT may use retrieved context to converse and reason. AtendIA validates
whether the source is allowed, healthy, current, tenant-scoped, bound to the
agent version, and sufficient for a factual answer.

The runtime must not invent a factual answer when a required source is missing,
unhealthy, stale, unbound, or unavailable.

## Source Types

Knowledge Sources are tenant-owned records with explicit type and purpose.
Allowed target source types:

- `faq`
- `catalog`
- `requirements`
- `policy`
- `process`
- `document`
- `url`
- `table`
- `expediente_contract`
- `prompt_reference`

Tenant-specific facts belong in tenant data or source documents. Shared runtime
code must not hardcode tenant, vertical, catalog, credit, price, requirement, or
workflow facts.

## Source Lifecycle

Every source must expose a lifecycle state:

- `draft`: created but not ready for agent binding.
- `uploaded`: raw asset exists but has not been parsed.
- `parsing`: ingestion is in progress.
- `indexed`: chunks or structured records exist.
- `ready`: source can be used by published agent versions.
- `stale`: freshness policy failed.
- `unhealthy`: parser, index, retrieval, ACL, or consistency checks failed.
- `disabled`: intentionally unavailable for new turns.
- `deleted`: removed from active use while preserving audit where required.

Only `ready` sources may satisfy required publish gates.

## Source Health Contract

A source health record must be visible to Publish Control, Agent Builder, Test
Lab, runtime trace, and admin diagnostics.

Minimum target fields:

- `tenant_id`
- `source_id`
- `source_type`
- `status`
- `parser_status`
- `index_status`
- `chunk_count` or `record_count`
- `checksum` or content version
- `freshness_policy`
- `last_ingested_at`
- `last_indexed_at`
- `last_retrieval_preview_at`
- `last_successful_query`
- `last_error_code`
- `last_error_message`
- `owner`
- `allowed_agent_versions`

Source health must be tenant-isolated. A tenant cannot pass readiness using
another tenant's source, source binding, index, or retrieval preview.

## Source Binding Contract

An agent version uses sources through explicit Source Bindings.

Minimum target binding fields:

- `tenant_id`
- `agent_version_id`
- `source_id`
- `source_type`
- `required`
- `priority`
- `mode`
- `allowed_tools`
- `audience_scope`
- `language_scope`
- `freshness_policy_override`
- `published_source_version`

Allowed binding modes:

- `answer_basis`: source may ground customer-facing factual claims.
- `tool_basis`: source backs a tenant-aware tool such as requirements lookup.
- `retrieval_context`: source can provide context but cannot alone validate a
  hard business fact.

Bindings are versioned with the agent version. A published agent must not drift
to a mutable draft source without Publish Control.

## Retrieval Preview Contract

Agent Builder and Test Lab must provide retrieval preview before publish.

Minimum target preview input:

- query text
- tenant id
- agent version id
- selected source ids
- source binding mode
- top-k
- language
- optional filter metadata

Minimum target preview output:

- matched source ids
- source version/checksum snapshot
- chunks or structured records returned
- relevance score or confidence
- citations or record references
- source health snapshot
- empty-result reason
- trace id

Retrieval preview is not a live readiness proof by itself. It becomes publish
evidence only when paired with Test Lab scenarios that exercise the same
published source bindings and runtime route.

## Publish Blockers

Publish Control must block publication when:

- a required source binding is missing
- a required source is not `ready`
- a required source is stale
- the source has zero chunks or records
- retrieval preview fails for a required factual domain
- the source tenant does not match the agent tenant
- ACL or audience scope is invalid
- a required tool depends on an unready source
- the source version differs from the version in the agent version snapshot
- the agent has no source for a factual domain it is configured to answer

The block must be visible as a readiness issue with source id, reason, severity,
and remediation owner.

## Runtime Rules

At runtime:

- ChatGPT receives only allowed, tenant-scoped, bound source context.
- Tools validate hard facts against source-backed contracts.
- Composer may write customer copy only from validated interpretation and
  allowed facts.
- Policy blocks unsupported factual claims.
- Missing required source means clarify, handoff, or no-send based on policy.
- Generic progress copy must not be used to mask missing sources.
- Fixtures cannot satisfy source readiness for live or publish gates.

## Trace Requirements

Every turn that uses or needs knowledge must record:

- active agent version
- source bindings considered
- retrieval query
- source health snapshot
- returned records/chunks
- tool results that used source-backed data
- unsupported claims blocked by policy
- final source basis for customer-facing factual claims

Trace text remains internal and never becomes customer copy.

## Product Surfaces

Knowledge Sources must be visible through:

- Knowledge Sources admin page
- Agent Builder source binding tab
- Publish Control readiness checklist
- Test Lab source panel and retrieval preview
- Inbox trace/debug view

## Future Tests

Future implementation for this contract must include unit or integration tests
for new or modified behavior, with 100% coverage of that behavior:

- required source missing blocks publish
- unhealthy required source blocks publish
- stale required source blocks publish
- zero-chunk source blocks publish
- retrieval preview uses only bound tenant sources
- tool basis source supports a tenant-aware tool result
- unsupported factual claim is blocked by policy
- no fixture-only source can prove live readiness
- trace includes source binding and health snapshot

Codex code review against base branch or uncommitted changes is required before
implementation handoff.

## Phase 4 Productized Implementation

Fase 4 productizes the documented contract in the no-live Agent Builder surface.
It does not activate runtime live behavior, WhatsApp, outbox, workflow side
effects, smoke, canary, or production traffic.

Implemented productized surface:

- `GET /api/v1/product-agents/knowledge-sources/options` lists tenant-scoped
  sources with health, status, checksum/version, last indexed timestamp,
  redacted errors, blockers, and bound agent ids.
- `GET /api/v1/product-agents/agents/{agent_id}/knowledge-bindings` lists
  source bindings for the agent draft version.
- `POST /api/v1/product-agents/agents/{agent_id}/knowledge-bindings` binds a
  tenant source to the mutable draft version only.
- `DELETE /api/v1/product-agents/agents/{agent_id}/knowledge-bindings/{id}`
  removes a draft binding only.
- `GET /api/v1/product-agents/agents/{agent_id}/readiness` evaluates draft
  readiness and keeps `test_lab_passed=false` and `live_publish_allowed=false`.

Readiness now blocks when:

- the agent has no knowledge source binding
- a required bound source is missing
- a required bound source is not healthy
- deployment safety flags are enabled

Agent Builder now has a `Knowledge` tab that shows available sources, connected
sources, source health, last indexed data, checksum/version, redacted errors,
and bind/unbind controls. It does not expose live activation.

## Phase 4 Acceptance

- source lifecycle states are documented
- source health contract is documented
- Source Binding contract is documented
- retrieval preview contract is documented
- publish blockers are documented
- runtime and trace rules are documented
- Product Agent Builder exposes a useful Knowledge tab
- backend exposes tenant-scoped sources and draft bindings
- readiness blocks missing or unhealthy sources
- Test Lab and live publish remain blocked in this phase
- no live/runtime/WhatsApp/outbox/workflow behavior was changed

Decision for this productized no-live phase:

`KNOWLEDGE_SOURCES_PRODUCTIZED_READY`
