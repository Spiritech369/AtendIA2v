# OpenAI Agent Builder Alignment Report

Date: 2026-06-06  
Scope: Research and specification only  
Official source reviewed: https://developers.openai.com/api/docs/guides/agent-builder/migrate-from-agent-builder  
Decision: `OPENAI_AGENT_BUILDER_ALIGNMENT_READY`

## Completed

- Summarized the official OpenAI migration guide.
- Mapped OpenAI Agent Builder concepts to AtendIA Product-First contracts.
- Defined AtendIA Agent Builder contract.
- Defined AtendIA AgentService runtime SDK equivalent.
- Defined product specs for Agent Builder, Test Lab, and Publish Control.
- Defined workflow-to-agent migration plan.
- Defined ChatGPT vs AtendIA separation of responsibility.
- Added OpenAI alignment ADRs.
- Updated `Arquitectura-Deseada.md` with OpenAI Agent Builder alignment.
- Adapted `spec.md`, `plan.md`, and `tasks.md` with the alignment phase.

## Safety Confirmation

This task did not:

- modify runtime code
- modify DB schema or migrations
- run Docker
- run WhatsApp
- activate send flags
- write outbox
- run smoke
- activate actions
- activate workflow events
- open canary
- open production
- fix Dinamo
- delete legacy

## Key Adoption

AtendIA adopts the pattern, not the implementation:

- Agent Builder maps to AtendIA Control Plane.
- Agents SDK maps to AtendIA AgentService runtime contract.
- Preview maps to DB-backed Test Lab.
- Create/deploy maps to Publish Control.
- Export/migration is not behavior proof.
- Representative Test Lab scenarios are required before publish.

## Final Decision

`OPENAI_AGENT_BUILDER_ALIGNMENT_READY`
