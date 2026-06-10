# OpenAI Agent Builder Migration Analysis

Date: 2026-06-06  
Status: Active research/specification  
Canonical AtendIA source: `Arquitectura-Deseada.md`  
Official source reviewed: https://developers.openai.com/api/docs/guides/agent-builder/migrate-from-agent-builder

## Executive Summary

OpenAI's migration guide confirms the Product-First direction for AtendIA:
builder/preview/deploy is a product control plane, while runtime, tools,
auth, permissions, and deployment must be validated by the application that
runs the agent.

The guide does not say migration is automatic. It explicitly warns that an
export does not convert the full workflow graph or guarantee unchanged
behavior. It also says control flow, triggers, tools, permissions, apps, skills,
authentication, and connections require manual review and testing before
creation or deployment.

For AtendIA, the adopted interpretation is:

- Agent Builder is AtendIA's tenant-facing Control Plane.
- AgentService is AtendIA's internal equivalent of an Agents SDK runtime.
- Test Lab is AtendIA's DB-backed Preview.
- Publish Control is AtendIA's deployment and approval layer.
- Workflow migration is classification and reconstruction, not blind export.
- ChatGPT reasons and drafts; AtendIA validates, executes, audits, sends, and
  publishes.

## What OpenAI Recommends

The guide recommends two migration paths:

- Agents SDK when the agent will run inside an application the developer builds
  and deploys.
- ChatGPT Workspace Agents when teams want to create agents through natural
  language and share them inside a workspace.

The guide describes exporting an Agent Builder workflow as TypeScript or Python
Agents SDK code, then continuing either inside an app runtime or by creating a
Workspace Agent from the export.

## Risks OpenAI Warns About

Required warnings that apply directly to AtendIA:

- export does not guarantee identical behavior
- export does not convert every workflow graph behavior
- some control flow may require manual recreation
- deterministic workflows may not migrate faithfully
- triggers, tools, permissions, apps, skills, authentication, and connections
  require separate review
- representative inputs must be tested before create/publish
- preview behavior must be compared against expected workflow behavior
- application owners using Agents SDK must validate runtime config, tools,
  authentication, permissions, and deployment

## What Applies To AtendIA

Applies strongly:

- Builder is a product surface, not runtime patching.
- Export/migration is only an input to design, not proof of correctness.
- Test/preview before publish is mandatory.
- Tools/actions require explicit schema, auth, permissions, and safety.
- Strongly deterministic flows may remain workflows.
- Runtime validation belongs to AtendIA.
- Deployment must be gated and reversible.

## What Does Not Apply Literally

AtendIA should not copy literally:

- ChatGPT Workspace Agents as the main runtime for tenant customer messaging.
- direct exported code as production behavior.
- one-off preview as live readiness.
- natural-language builder output as tenant-validated configuration without
  AtendIA checks.
- OpenAI Agent Builder graph semantics as a guaranteed AtendIA workflow model.

## Relationship To `Arquitectura-Deseada.md`

The guide reinforces:

- Control Plane must own configuration.
- Runtime Plane must run inside AtendIA.
- Test Lab must validate before publish.
- Publish Control must block unsafe deployments.
- Tools/actions/workflows need permissions and safety.
- Deterministic processes should not be forced into LLM behavior.
- `TurnOutput.final_message` must stay the visible response authority.

No architectural contradiction was found. The guide strengthens the existing
Product-First plan and adds explicit migration review gates for workflows,
tools, auth, permissions, and deployment.

## Decisions To Adopt

AtendIA should adopt:

- OpenAI Agent Builder pattern as inspiration for Control Plane.
- Agents SDK pattern as inspiration for AgentService runtime contract.
- Preview pattern as DB-backed Test Lab.
- manual migration review for workflows.
- representative input suites before publish.
- separate validation of tools, auth, permissions, deployment, and safety.
- explicit limitations for deterministic workflows.

Final research decision:

`OPENAI_AGENT_BUILDER_GUIDE_ALIGNED_WITH_PRODUCT_FIRST`
