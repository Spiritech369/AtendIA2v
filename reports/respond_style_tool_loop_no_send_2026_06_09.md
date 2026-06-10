# Respond-Style Tool Loop No-Send - 2026-06-09

## Decision

`PHASE_5_RESPOND_STYLE_TOOL_LOOP_NO_SEND_READY`

## Scope

Implemented Phase 5: `PHASE_5_RESPOND_STYLE_TOOL_LOOP_NO_SEND`.

This phase adds an isolated no-live Respond-Style tool loop:

```txt
LLM turn 1
-> tool proposals
-> AtendIA dry/fact-only tool executor
-> tool_results added to AgentContextPackage
-> LLM turn 2
-> RespondStyleTurnValidator
-> FinalTurnDecision always no_send
```

The loop is not connected to WhatsApp, smoke, live outbox, live SendAdapter,
AgentService, ConversationRunner, legacy composers, real workflow execution, or
real action execution.

## Implemented Files

- `core/atendia/agent_runtime/respond_style_tool_loop.py`
- `core/tests/agent_runtime/test_respond_style_tool_loop.py`
- `tools/run_respond_style_tool_loop_no_send_2026_06_09.py`
- Lazy exports in `core/atendia/agent_runtime/__init__.py`
- Capability guidance updates in `core/atendia/agent_runtime/respond_style_llm_provider.py`

## Tool Loop Architecture

`RespondStyleToolLoop` receives:

- `AgentTurnInput`
- `AgentContextPackage`
- injected `RespondStyleTurnProvider`
- injected `RespondStyleToolExecutor`

It then:

1. Calls the provider for the first Respond-Style turn.
2. Reads validated `LLMToolCallProposal` items from the first decision.
3. Executes at most one tool round through the injected executor.
4. Adds fact-only `ToolExecutionResult` records to `context.tool_results`.
5. Calls the provider again with the enriched context.
6. Returns a fail-closed `FinalTurnDecision` with `send_decision="no_send"`.

The loop blocks no-send when:

- a required tool is not bound
- a required tool fails
- a required tool is skipped
- a second provider turn still contains a required pending tool request after
  the one allowed tool round

## Tool Execution Contract

`ToolExecutionResult` includes:

- `tool_name`
- `status`: `succeeded`, `failed`, or `skipped`
- `facts`
- `citations`
- `source_refs`
- `error_code`
- `is_required`
- `can_support_claims`

The model forbids extra fields, so tool results cannot carry customer-facing
copy such as `final_message` or `customer_copy`.

## Provider Guidance

The provider prompt was updated generally, not by tenant or phrase-specific
routing:

- read `tool_schemas` as capabilities
- use descriptions, capabilities, preconditions, and required context keys
- if contact/conversation state identifies a requested fact and preconditions
  are satisfied, propose the matching tool
- if preconditions are missing, ask for the missing detail naturally
- tools return facts only
- when `tool_results` exist, write `final_message` from those facts
- do not request the same succeeded tool again

## What This Does Not Execute

- no WhatsApp
- no smoke
- no live outbox writes
- no live SendAdapter
- no AgentService integration
- no ConversationRunner
- no HumanResponseComposer
- no StructuredRuntimeComposer
- no workflow side effects
- no action side effects
- no field writes
- no deterministic customer-copy fallback

## Tests

Command:

```powershell
$env:PYTHONPATH='core'; & 'core\.venv\Scripts\python.exe' -m pytest core/tests/agent_runtime/test_respond_style_turn_contract.py core/tests/agent_runtime/test_respond_style_turn_validator.py core/tests/agent_runtime/test_respond_style_llm_provider.py core/tests/agent_runtime/test_respond_style_tool_loop.py
```

Result:

- `48 passed in 0.34s`

Command:

```powershell
$env:PYTHONPATH='core'; & 'core\.venv\Scripts\python.exe' -m ruff check core/atendia/agent_runtime/respond_style_llm_provider.py core/atendia/agent_runtime/respond_style_tool_loop.py core/tests/agent_runtime/test_respond_style_llm_provider.py core/tests/agent_runtime/test_respond_style_tool_loop.py tools/run_respond_style_tool_loop_no_send_2026_06_09.py
```

Result:

- `All checks passed`

Coverage added for:

- loop executes a tool proposed by the LLM/provider
- tool result is visible to the second provider turn
- final message can use tool facts
- price without quote evidence stays no-send after validator retry
- requirements without requirements evidence stays no-send after validator retry
- required tool failure blocks no-send
- required skipped/unbound tool blocks no-send
- skipped tool result cannot carry customer copy
- second-turn required pending tool request blocks no-send
- fake executor has no delivery/workflow/action side effects
- no unsafe legacy/live imports in the loop
- no tenant/vertical hardcodes in the loop
- no routing by customer phrases in the loop source

## OpenAI No-Send Runner

Command:

```powershell
$env:PYTHONPATH='core'; & 'core\.venv\Scripts\python.exe' tools/run_respond_style_tool_loop_no_send_2026_06_09.py
```

Result:

- decision: `PHASE_5_RESPOND_STYLE_TOOL_LOOP_NO_SEND_READY`
- mode: `no_send`
- key source: `core\.env:ATENDIA_V2_OPENAI_API_KEY`
- side effects: `outbox=false`, `workflows=false`, `actions=false`

Runner scenario outcomes:

- `requirements_with_preconditions`: OpenAI proposed `requirements.lookup`;
  dry executor returned requirement facts; second LLM turn produced a valid
  no-send `final_message` from those facts.
- `requirements_missing_preconditions`: no tool was executed; final message
  asked for the missing selected option without inventing requirements.
- `price_missing_or_quote_context`: OpenAI proposed `quote.resolve`, dry
  executor skipped with `missing_selected_option`, and the loop blocked
  fail-closed no-send with no customer copy.
- `price_objection`: OpenAI proposed `alternate_product_search`; dry executor
  returned fact-only alternatives; second LLM turn produced a valid no-send
  response from those facts.

## Safety Audit

The runtime loop source was checked for unsafe live/legacy references and does
not contain:

- `ConversationRunner`
- `HumanResponseComposer`
- `StructuredRuntimeComposer`
- `SendAdapter`
- `enqueue_messages`
- `evaluate_event`
- `outbox`

The runtime loop source was also checked for prohibited tenant/vertical
hardcodes and does not contain Dinamo, motos, credito, credito with accent, SAT,
or Metro terms.

## Rollback

Rollback is code-only:

1. Remove `core/atendia/agent_runtime/respond_style_tool_loop.py`.
2. Remove `core/tests/agent_runtime/test_respond_style_tool_loop.py`.
3. Remove `tools/run_respond_style_tool_loop_no_send_2026_06_09.py`.
4. Remove the Fase 5 lazy exports from `core/atendia/agent_runtime/__init__.py`.
5. Revert the general capability guidance added to
   `respond_style_llm_provider.py` if needed.

No data, DB state, live deployment, SendAdapter, workflow, action, outbox, or
WhatsApp state is modified by this phase.
