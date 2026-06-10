# AtendIA Agent Builder Contract

Date: 2026-06-06  
Status: Active architecture contract  
Canonical source: `Arquitectura-Deseada.md`

## Purpose

AtendIA Agent Builder is the tenant-facing product surface for creating,
configuring, testing, publishing, pausing, auditing, and rolling back
configurable AI agents.

It follows the Agent Builder pattern but remains AtendIA-controlled:
configuration is tenant-scoped, versioned, validated, tested, published, and
traceable before live traffic.

## Agent Product Entity

Minimum target fields:

- `tenant_id`
- `agent_id`
- `agent_version_id`
- `name`
- `role`
- `tone`
- `language`
- `instructions`
- `prompt_blocks`
- `knowledge_source_bindings`
- `tool_bindings`
- `action_bindings`
- `field_permissions`
- `lifecycle_permissions`
- `workflow_bindings`
- `handoff_rules`
- `safety_policy`
- `test_suites`
- `publish_state`
- `rollback_target`

## Version Rules

- Draft and Published are not the same.
- Published agents run from immutable versions.
- Draft edits do not affect live behavior until a new publish is approved.
- Every publish requires DB-backed Test Lab passed.
- Every published agent has trace and rollback metadata.
- Rollback targets must be approved prior versions.

## Builder Responsibilities

Agent Builder must configure:

- identity and role
- tone and language policy
- instructions and prompt blocks
- Knowledge Source bindings
- allowed tools
- allowed actions
- writable fields and evidence rules
- lifecycle transitions
- workflow event bindings
- handoff rules
- safety policy
- Test Lab scenarios
- publish state and rollback target

## ChatGPT vs AtendIA

ChatGPT can draft and reason about configuration suggestions.

AtendIA must validate:

- tenant scope
- source availability
- tool/action permissions
- field write permissions
- workflow safety
- publish readiness
- rollback metadata

## Publish Rules

Publish is blocked unless:

- required sources are ready
- required tools are configured
- required auth/permissions are present
- Test Lab passed
- trace is complete
- Policy passes
- no legacy visible path is available
- no-send/live-candidate parity passes when send is in scope
- rollback target exists

## Non-Goals

Agent Builder must not:

- patch runtime behavior directly
- create tenant-specific rules in shared code
- publish from natural language alone
- bypass Test Lab
- bypass Publish Control
- send WhatsApp
- write outbox
- execute workflows live

## Future Tests

Future implementation must test new or modified behavior with 100% coverage for
the changed behavior:

- draft edits do not affect published version
- published version is immutable
- publish blocked without Test Lab passed
- publish blocked without source/tool/auth readiness
- rollback target required for live-limited publish
- tenant cannot bind another tenant's source/action/workflow
- trace exists for published agent turns

Codex code review is required before implementation handoff.
