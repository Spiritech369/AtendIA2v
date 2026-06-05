# AgentRuntime v2 Conversation Preview

This task adds an experimental, manual backend path for running AgentRuntime v2 against real conversations. It does not replace the webhook runner and it does not activate automatic sending.

## Flags

Environment variables use the normal `ATENDIA_V2_` prefix:

- `ATENDIA_V2_AGENT_RUNTIME_V2_ENABLED=false`
- `ATENDIA_V2_AGENT_RUNTIME_V2_SEND_ENABLED=false`
- `ATENDIA_V2_AGENT_RUNTIME_V2_ACTIONS_ENABLED=false`

Preview and send both require `AGENT_RUNTIME_V2_ENABLED`. Send also requires `AGENT_RUNTIME_V2_SEND_ENABLED`.

## Endpoints

### Preview

```http
POST /api/v1/conversations/{conversation_id}/agent-runtime-v2/preview
```

Requires tenant admin. It:

- loads the real tenant-scoped conversation;
- builds `TurnContext` with `ContextBuilder`;
- retrieves Knowledge OS snippets;
- runs `AgentRuntime`;
- validates output through `PolicyValidator`;
- records a compatible `turn_traces` row;
- returns full `TurnOutput` plus debug metadata.

It does not persist outbound messages, stage outbox jobs, send WhatsApp, move lifecycle, update contact fields, or execute actions.

### Send

```http
POST /api/v1/conversations/{conversation_id}/agent-runtime-v2/send
```

Requires tenant admin plus:

- `AGENT_RUNTIME_V2_ENABLED=true`
- `AGENT_RUNTIME_V2_SEND_ENABLED=true`
- valid `TurnOutput`
- policy-valid output
- active conversation
- no `conversation_state.bot_paused`
- no open human handoff
- latest inbound inside the WhatsApp 24h free-form window

Send stages through `outbound_outbox` via `stage_outbound(...)` and creates a queued outbound `messages` row with the same id. It does not call Meta, Baileys, or any channel adapter directly.

Actions are executed in dry-run by default. Real action execution requires `AGENT_RUNTIME_V2_ACTIONS_ENABLED=true`.

## Trace

Both preview and send write a compatible `turn_traces` row:

- `router_trigger`: `agent_runtime_v2_preview`, `agent_runtime_v2_send`, or policy error variants
- `composer_input`: context summary
- `composer_output`: serialized `TurnOutput`
- `kb_evidence`: citations and retrieval metadata
- `errors`: policy issues when present
- `outbound_messages`: populated only for send

`composer_provider` is normalized to legacy-compatible values (`openai` or `fallback`) to avoid a migration in this task.

## Local Testing

```bash
cd core
ATENDIA_V2_AGENT_RUNTIME_V2_ENABLED=true \
python -m pytest tests/api/test_agent_runtime_v2_conversation_preview.py
```

To test send locally, also set:

```bash
ATENDIA_V2_AGENT_RUNTIME_V2_SEND_ENABLED=true
```

The send endpoint stages outbox rows only; the existing outbox worker is responsible for actual delivery.

## Safety Boundaries

- No webhook runner replacement.
- No automatic execution.
- No direct channel send.
- No send on policy failure.
- No productive action execution unless explicitly enabled.
- Tenant scoping is enforced before any runtime call.
