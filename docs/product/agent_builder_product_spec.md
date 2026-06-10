# Agent Builder Product Spec

Date: 2026-06-06  
Status: Product specification  
Canonical source: `Arquitectura-Deseada.md`

## Objective

Let each tenant create, configure, test, publish, pause, audit, and roll back AI
agents without editing shared runtime code.

## Primary Users

- tenant admin
- operations manager
- agent designer
- support/sales lead
- platform admin

## Core Screens

- Agent list
- Agent draft editor
- Prompt blocks
- Knowledge bindings
- Tools/actions bindings
- Field/lifecycle permissions
- Workflow bindings
- Handoff rules
- Safety policy
- Test suites
- Publish readiness
- Version history and rollback

## Required Capabilities

- create draft agent
- edit identity, role, tone, language, instructions
- attach prompt blocks
- bind Knowledge Sources
- bind tools and actions
- configure field permissions
- configure lifecycle permissions
- configure workflow event bindings
- configure handoff rules
- attach Test Lab suites
- view readiness blockers
- request publish approval
- pause deployment
- roll back to approved version

## Product Rules

- Draft edits do not affect Published.
- Published version is immutable.
- Publish requires DB-backed Test Lab passed.
- Publish requires source/tool/auth/permission readiness.
- Publish requires rollback target for live-limited scope.
- No tenant-specific behavior may be written into shared runtime.
- Any live scope requires explicit approval.

## Evidence

Agent Builder must show:

- active draft version
- immutable version history without presenting live activation as available in
  this no-live phase
- source health
- tool/action readiness
- workflow readiness
- Test Lab last run
- Publish Control state
- rollback target
- trace availability

## Knowledge Tab

The Product-First Builder Knowledge tab must show:

- tenant-scoped available sources
- sources bound to the mutable draft version
- source type, status, health, checksum/version, and last indexed timestamp
- redacted source error when present
- missing-source and unhealthy-source readiness blockers
- bind/unbind controls for draft only

The tab must not activate WhatsApp, live send, outbox, workflows, actions,
smoke, canary, or production traffic.

## Tools Tab

The Product-First Builder Tools tab must show:

- tenant-available fact tools
- tools bound to the mutable draft version
- capability key, label, category, risk, schemas, and side-effect type
- `side_effect_type=none` for every tool
- bind/unbind controls for draft only

Tools resolve facts. They must not produce side effects, update state, trigger
workflows, call external systems, or send customer messages.

## Actions Tab

The Product-First Builder Actions tab must show:

- tenant-available actions
- actions added to the mutable draft version
- action key, label, category, risk, execution mode, side-effect type, auth
  requirements, required permissions, and publish blockers
- disabled-by-default action binding for this no-live phase
- `send_message` only as a blocked SendAdapter boundary

Actions produce effects. The Builder may configure disabled or dry-run/approval
metadata, but it must not execute actions, trigger workflows, call webhooks,
write outbox, or send messages.

## Acceptance

This spec is complete when it maps to:

- `docs/architecture/atendia_agent_builder_contract.md`
- `docs/product/agent_test_lab_spec.md`
- `docs/product/agent_publish_control_spec.md`

No runtime implementation is part of this spec phase.
