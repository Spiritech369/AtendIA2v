# Workflow To Agent Migration Plan

Date: 2026-06-06  
Status: Active migration specification  
Official source reviewed: https://developers.openai.com/api/docs/guides/agent-builder/migrate-from-agent-builder

## Purpose

Define how AtendIA migrates existing workflows into Product-First agents when
appropriate, and when workflows should remain deterministic automations.

## Core Rule

Not every workflow should become an agent. Strongly deterministic flows can
remain workflows and be called by the agent through approved actions/events.

## Classification

| Classification | Meaning | Migration Path |
|---|---|---|
| Conversational Agent Behavior | Natural language interpretation, clarification, response drafting | Move to Agent Builder prompt/policy/tests |
| Tool / Action | Structured lookup, write, API call, side effect | Move to Tool or Action Registry binding |
| Workflow Automation | Operational process after agent event | Keep workflow, bind via Workflow Binding |
| Human Review | Requires operator judgment | Handoff or approval gate |
| Deterministic Process | Must execute exact ordered logic | Keep workflow, expose as action/event if needed |
| Not Migratable Yet | Missing auth, permissions, source, tests, trace, or rollback | Block until dependencies exist |

## Migration Steps

1. Inventory workflow triggers, nodes, tools, outputs, permissions, and side
   effects.
2. Classify each behavior using the migration table.
3. Identify behavior requiring manual recreation.
4. Define tools/actions with schemas, auth, permissions, and idempotency.
5. Define workflow-side triggers that remain workflow-side.
6. Create representative Test Lab scenarios.
7. Compare migrated behavior against expected original workflow behavior.
8. Block publish until Test Lab, trace, permissions, and rollback pass.

## Validation

Migrated behavior must prove:

- same expected customer-visible outcome
- no workflow overwrites `TurnOutput.final_message`
- no side effects in no-send
- tools/actions have auth and permissions
- deterministic steps remain deterministic
- representative inputs pass
- trace explains differences

## OpenAI Alignment

OpenAI's migration guide warns that export/migration does not guarantee
identical behavior and that control flow, triggers, tools, and permissions need
manual review. AtendIA adopts that as a migration gate.

Decision:

`WORKFLOW_TO_AGENT_MIGRATION_REQUIRES_MANUAL_REVIEW_AND_TEST_LAB`
