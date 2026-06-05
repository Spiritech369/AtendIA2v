# AgentRuntime v2 Automatic Shadow Mode

Date: 2026-05-31

## Purpose

Automatic shadow mode runs AgentRuntime v2 against real inbound turns without
replacing the legacy `ConversationRunner`. It is an observability path only:
legacy remains the production authority for response generation, outbox writes,
state updates and workflow behavior.

## Where It Runs

Real Meta and Baileys inbound messages are persisted first, then collapsed by
`process_inbound_burst`. That worker runs `ConversationRunner` and commits the
legacy turn. After that commit, it opens a separate DB session and calls
`AgentRuntimeShadowService`.

This sequencing means:

- legacy outbound is not delayed by shadow persistence;
- a shadow exception cannot rollback the legacy turn;
- the webhook/worker returns the same legacy status even if shadow fails.

## Gates

Shadow runs only when all are true:

- global `ATENDIA_V2_AGENT_RUNTIME_V2_ENABLED=true`;
- tenant policy allows `shadow_mode_enabled=true`;
- optional `allowed_agent_ids` allows the assigned agent;
- optional `allowed_channel_ids` allows the conversation channel;
- the conversation belongs to the tenant;
- no shadow trace already exists for the same inbound message and runtime version.

The tenant policy lives in `tenants.config.agent_runtime_v2`.

## No Side Effects

Shadow mode:

- does not send WhatsApp;
- does not stage outbox;
- does not write customer fields;
- does not move lifecycle;
- does not execute actions;
- does not emit real workflow events.

The only write is a `TurnTrace` with `router_trigger=agent_runtime_v2_shadow_auto`.

## Idempotency

Idempotency is based on:

```text
tenant_id + conversation_id + inbound_message_id + agent_runtime_v2_shadow_v1
```

Before running, the service checks for an existing shadow `TurnTrace` with the
same tenant, conversation, inbound message and router trigger.

## Trace And Comparison

The shadow `TurnTrace` stores:

- legacy trace id when available;
- legacy outbound text when available;
- v2 `TurnOutput`;
- v2 confidence;
- citations;
- actions proposed;
- field updates proposed;
- lifecycle proposal;
- policy result;
- comparison summary;
- rollout decisions;
- explicit side-effect flags, all false.

Policy failures are saved in `errors`; provider failures produce a shadow trace
with status information instead of breaking legacy.

## Current Limitations

- Shadow is integrated into the burst worker, which is the normal Meta/Baileys
  automatic inbound path. Direct test-only runner paths may not invoke it.
- There is no background retry for failed shadow runs yet.
- Comparison is deterministic and structural; no LLM judge is used.
- There is no database unique constraint for idempotency yet; the service uses
  a pre-run trace lookup.
