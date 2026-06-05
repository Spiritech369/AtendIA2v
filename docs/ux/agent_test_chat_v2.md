# Agent Test Chat v2

## Purpose

Agent Test Chat v2 is a tenant-admin test surface for `agent_runtime_v2`.

It lets an operator run a dry-run turn against:

- AgentRuntime v2
- Knowledge OS citations
- proposed field updates
- proposed lifecycle updates
- proposed actions
- policy/debug metadata

The UI does not persist a real conversation, send WhatsApp, move lifecycle,
update customer fields or execute real actions.

## Location

Agents -> selected agent -> `Pruebas` tab -> `Agent Test Chat v2`.

## Flow

1. The operator types a customer test message.
2. Optional simulated context can be provided:
   - lifecycle stage;
   - knowledge source ids;
   - visible contact field definitions.
3. The frontend calls:

```http
POST /api/v1/agents/{agent_id}/test-turn-v2
```

4. The response is appended to local in-memory test history.
5. The details panel shows:
   - final message;
   - sources used;
   - field updates;
   - lifecycle update;
   - actions;
   - confidence;
   - risk flags;
   - needs human;
   - policy/debug;
   - trace metadata.

## Safety

The surface is labeled `Test mode / Dry run`.

The request includes metadata:

```json
{
  "surface": "agent_test_chat_v2",
  "dry_run": true
}
```

Backend policy remains authoritative. Policy errors are rendered in the chat as
legible issue codes/messages.

## Current Scope

Implemented:

- local test history;
- message textarea;
- simulated lifecycle stage;
- optional knowledge source ids;
- editable contact field definitions JSON;
- citations/source cards;
- JSON inspectors for field updates, lifecycle, actions and debug;
- frontend tests for render, success and policy error states.

Not implemented yet:

- Eval Lab datasets;
- batch runs;
- persisted test sessions;
- side-by-side agent comparison;
- real workflow/action execution from the UI;
- rich source card previews.
