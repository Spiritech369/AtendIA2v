# AtendIA Agent Runtime SDK Contract

Date: 2026-06-06  
Status: Active architecture contract  
Canonical source: `Arquitectura-Deseada.md`

## Purpose

AgentService is AtendIA's internal equivalent to an Agents SDK runtime: the
application-owned execution path for published agent versions.

OpenAI provides the model and APIs. AtendIA owns tenant config, tools, auth,
permissions, state, policy, publish, send, trace, and rollback.

## Input Contract

Minimum input:

- `tenant_id`
- `agent_deployment_id`
- `agent_version_id`
- `contact_id`
- `conversation_id`
- `inbound_message`
- `attachments`
- `send_mode`

## Runtime Flow

1. Load active deployment.
2. Load published agent version.
3. Load tenant knowledge bindings.
4. Load recent conversation.
5. Load contact memory.
6. Build context.
7. Call ChatGPT / semantic provider.
8. Execute allowed tools.
9. Validate tools.
10. StateWriter persists only evidenced changes.
11. Composer creates `TurnOutput.final_message`.
12. Policy validates.
13. SendAdapter decides no-send/live.
14. Universal trace records everything.

## Output Contract

Minimum output:

- `TurnOutput.final_message`
- `tool_results`
- `field_updates`
- `lifecycle_update`
- `workflow_events`
- `action_events`
- `send_decision`
- `trace_id`

## Runtime Rules

- No-send/live use the same route.
- Required tool failed means no-send.
- Required source unavailable means no-send, clarify, or handoff by policy.
- Policy failed means no-send.
- Internal text is never visible.
- Workflow cannot overwrite final message.
- Legacy cannot be visible for published Runtime V2 agents.
- Tools/actions return structured data, not final customer copy.
- SendAdapter is the only customer delivery path.

## ChatGPT vs AtendIA

ChatGPT can:

- understand intent
- handle ambiguity
- propose candidate fields
- select allowed tools
- draft natural copy
- summarize context
- translate
- interpret normalized multimodal signals

ChatGPT cannot:

- save state directly
- send WhatsApp
- write outbox
- execute workflows directly
- decide permissions
- decide approval
- invent prices or requirements
- validate expediente completion
- ignore policy
- access unpublished sources
- publish agents
- roll back deployments

AtendIA must:

- control tenant and deployment
- validate runtime config
- authorize knowledge
- execute tools/actions
- validate outputs
- persist state
- control lifecycle
- control publish
- control send/no-send
- generate trace
- handle rollback
- block risks

## Future Tests

Future implementation must include unit/integration tests with 100% coverage
for changed behavior:

- no-send/live route parity
- required tool failure no-send
- policy failure no-send
- internal text never visible
- workflow cannot overwrite final message
- legacy cannot produce visible output
- trace records every decision
- SendAdapter is the only delivery path

Codex code review is required before implementation handoff.
