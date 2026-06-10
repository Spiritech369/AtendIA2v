# OpenAI Agent Builder Alignment ADRs

Date: 2026-06-06  
Status: Active decisions  
Official source reviewed: https://developers.openai.com/api/docs/guides/agent-builder/migrate-from-agent-builder

## ADR-001 - AtendIA Adopts Agent Builder Pattern As Control Plane

**Decision**: AtendIA adopts the Agent Builder pattern as a tenant-scoped
Control Plane for configurable agents.

**Consequence**: Builder output must be validated by AtendIA before publish.

## ADR-002 - AgentService Is AtendIA's Runtime Equivalent To Agents SDK

**Decision**: AgentService is the application-owned runtime path for AtendIA
agents.

**Consequence**: AtendIA validates runtime config, tools, auth, permissions, and
deployment.

## ADR-003 - Test Lab DB-Backed Replaces Fixture-Only Preview

**Decision**: Preview maps to DB-backed Test Lab, not fixture-only smoke.

**Consequence**: Publish readiness requires the same route as live with
SendAdapter in no-send.

## ADR-004 - Deterministic Workflows Remain Workflows

**Decision**: Strong deterministic workflows should stay workflows unless
manual migration and tests prove agent suitability.

**Consequence**: Agents can emit events or request actions; they do not absorb
every workflow.

## ADR-005 - Tools And Actions Require Explicit Permissions And Auth

**Decision**: Tools/actions require schema, permissions, auth, and publish
readiness before live use.

**Consequence**: Missing auth/permissions blocks publish.

## ADR-006 - Migration Does Not Guarantee Identical Behavior

**Decision**: Export or migration is not behavior proof.

**Consequence**: Representative Test Lab scenarios are required.

## ADR-007 - `TurnOutput.final_message` Remains The Only Visible Output

**Decision**: OpenAI alignment does not change AtendIA's final message
authority.

**Consequence**: Workflows, tools, fallbacks, recovery paths, and legacy cannot
write customer-visible copy.
