# Agent Runtime v2

## Why it exists

AtendIA currently has several layers that can decide, write state, move pipeline, or draft customer-facing copy. `agent_runtime_v2` creates one new boundary: the agent produces a single `TurnOutput`; everything else consumes that contract.

The target architecture is:

`AgentRuntime` converses. `Knowledge` informs. `Actions` execute. `Lifecycle` measures. `Workflows` automate. `Policy` validates.

## What it replaces conceptually

The v2 runtime is the future replacement boundary for scattered decision/copy authority across `conversation_runner`, composer, response contracts, response frames, tool-visible text, and pipeline movement logic.

It does not delete those pieces yet. It gives the migration a stable contract so each old responsibility can be moved deliberately.

## What it does not replace yet

This first implementation does not replace `ConversationRunner`, WhatsApp dispatch, outbound outbox, customer field persistence, lifecycle transitions, workflow execution, handoff creation, or real LLM calls.

The feature flag `ATENDIA_V2_AGENT_RUNTIME_V2_ENABLED=false` is off by default. The package can be used by tests or an internal harness, but production behavior stays on the legacy runner.

## TurnOutput

`TurnOutput` is the single output of one agent turn:

- `final_message`: one string, and the only customer-facing response authority.
- `actions`: structured `ActionRequest` values for post-turn execution.
- `field_updates`: proposed customer/contact field writes.
- `lifecycle_update`: optional lifecycle or pipeline proposal.
- `knowledge_citations`: sources used by the agent.
- `confidence`: numeric confidence in `[0, 1]`.
- `needs_human`: whether the turn should be handed off or reviewed.
- `risk_flags`: audit flags such as low confidence or sensitive action.
- `trace_metadata`: optional diagnostics.

Actions and tools return data only. They do not return final visible copy. The v2
schemas reject unexpected output fields and customer-visible text keys such as
`final_message`, `message`, `reply`, or `visible_text` outside
`TurnOutput.final_message`.

## Runtime pieces

- `ContextBuilder` prepares canonical context: tenant, conversation, customer, recent messages, contact fields, lifecycle state, active agent, and metadata. Knowledge snippets are a TODO-backed empty adapter until Knowledge OS is wired in.
- `AgentRuntime` calls a provider and returns only `TurnOutput`. The default provider is deterministic for tests.
- `PolicyValidator` enforces contract safety before callers execute actions.
- `ActionRegistry` defines the initial action surface: `update_contact_field`, `move_lifecycle`, `assign_conversation`, `add_tag`, `trigger_workflow`, `call_webhook`, and `close_conversation`.
- `PostTurnActionExecutor` executes actions after the final response exists. In this phase it validates policy before execution, dry-runs known actions, and refuses unknown or unsafe actions.
- `tracing.py` contains small helpers for runtime trace metadata.

## Future ConversationRunner integration

The next migration task should add an internal/manual path guarded by `agent_runtime_v2_enabled`. The legacy runner should continue as fallback until v2 can persist traces, enqueue outbound messages, and execute actions through audited services.

The integration order should be:

1. Build `TurnContext` from the existing runner state.
2. Call `AgentRuntime.run_turn`.
3. Persist a turn trace with `TurnOutput`.
4. Send `final_message` through the existing outbound policy/outbox.
5. Execute actions through `PostTurnActionExecutor` with real handlers.
6. Keep rollback to `ConversationRunner` until tenant-level evaluation passes.

## Running tests

From the repo root:

```powershell
cd core
uv run pytest tests/agent_runtime
```

If `uv` is not available, use the project Python environment:

```powershell
cd core
pytest tests/agent_runtime
```
