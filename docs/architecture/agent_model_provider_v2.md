# Agent Model Provider v2

AgentRuntime v2 now has an optional model-provider layer for real LLM generation while keeping `TurnOutput` as the only runtime output contract.

## Files

- `core/atendia/agent_runtime/model_provider.py`
- `core/atendia/api/agents_routes.py`

## Interface

`AgentModelProvider` exposes:

```python
generate_turn(context, agent_config, evidence_pack) -> TurnOutputDraft
```

`TurnOutputDraft` is an alias of `TurnOutput` in v1. The provider may produce a draft, but it still has to validate against the same structured contract before the runtime policy layer sees it.

## Providers

- `MockAgentProvider`: deterministic tests and disabled-model mode.
- `SafeFallbackAgentProvider`: safe handoff output when a configured model path is unavailable.
- `OpenAIAgentProvider`: optional OpenAI chat-completions provider using JSON schema response format and Pydantic validation.

Anthropic is not implemented in this task. The existing Anthropic path is NLU fallback-specific, and adding a second structured output adapter would expand scope.

## Flags

Defaults keep production unchanged:

- `ATENDIA_V2_AGENT_RUNTIME_V2_ENABLED=false`
- `ATENDIA_V2_AGENT_RUNTIME_V2_MODEL_PROVIDER=disabled`
- `ATENDIA_V2_AGENT_RUNTIME_V2_MODEL=gpt-4o-mini`

The Test Chat runtime builder asks `build_agent_turn_provider()`. If runtime v2 or the model provider flag is off, it receives `MockAgentProvider`, not OpenAI.

## Prompt Base

The system prompt requires the model to:

- answer the current question first;
- use Knowledge citations as source of truth;
- not invent prices, schedules, policies, availability, requirements, or documents;
- ask at most one question;
- avoid sounding like a form;
- propose field updates, actions, or lifecycle changes only with evidence;
- escalate when confidence is low, risk is high, the customer asks for a human, or knowledge is missing;
- return JSON compatible with `TurnOutput`;
- never place customer-visible text inside actions.

Vertical behavior must come from agent instructions, enabled knowledge sources, and eval blueprints, not from the base prompt.

## Structured Output Safety

OpenAI output flow:

1. Request JSON through `response_format={"type": "json_schema"}`.
2. Parse JSON.
3. Validate with `TurnOutput`.
4. If parsing/validation fails, ask for one JSON-only repair.
5. Normalize safety-sensitive output:
   - low confidence sets `needs_human=true` and `low_confidence`;
   - missing model citations when Knowledge citations were available sets
     `needs_human=true` and `missing_required_citations`;
   - provider trace metadata records provider/model/latency.
6. Run `PolicyValidator` inside the provider before returning the draft.
7. If repair fails or policy rejects the draft, return a safe
   `needs_human=true` fallback.
8. AgentRuntime still runs `PolicyValidator` as the final guard.

No unvalidated free text is returned from the provider.

## Mocked Provider Tests

`core/tests/agent_runtime/test_agent_model_provider_v2.py` exercises the real
`OpenAIAgentProvider` path with a fake SDK client. These tests do not call the
external OpenAI API and do not enable the provider by default.

Covered cases:

- valid JSON without repair;
- invalid JSON with successful repair;
- invalid JSON with failed repair;
- SDK timeout fallback;
- unknown action rejected by provider policy validation;
- `final_message` inside action payload rejected;
- field update missing evidence/confidence rejected;
- low confidence escalates to `needs_human`;
- missing citations when Knowledge was available escalates safely;
- fallback output remains a valid `TurnOutput`.

## Pending

- Anthropic structured-output adapter.
- Tenant-level model selection for AgentRuntime v2.
- Usage/cost accounting in trace metadata.
- Optional stricter OpenAI schema once free-form payload metadata is split from action inputs.
