# Respond-Style LLM Turn Provider No-Send - 2026-06-09

## Scope

Implemented Phase 4: `RESPOND_STYLE_LLM_TURN_PROVIDER_NO_SEND`.

This phase creates an isolated no-live provider that uses the Respond-Style Turn
Contract to request an `LLMAgentTurnOutput` from an OpenAI-compatible client,
validates it with `RespondStyleTurnValidator`, and returns a no-send
`FinalTurnDecision`.

The provider is not connected to `AgentService`, WhatsApp, outbox, live
`SendAdapter`, workflow execution, action execution, `ConversationRunner`, or
legacy customer-facing composers.

## Implemented Files

- `core/atendia/agent_runtime/respond_style_llm_provider.py`
- `core/tests/agent_runtime/test_respond_style_llm_provider.py`
- `tools/run_respond_style_llm_provider_no_send_2026_06_09.py`
- Lazy exports in `core/atendia/agent_runtime/__init__.py`

## Provider Behavior

`RespondStyleLLMTurnProvider.generate()` receives:

- `AgentTurnInput`
- `AgentContextPackage`

It then:

1. Builds system/user messages from tenant agent identity, instructions, recent
   transcript, contact state, retrieved context, tool schemas, field policies,
   workflow trigger schemas, action schemas, handoff policy, and hard policies.
2. Calls an OpenAI-compatible async chat client with strict JSON schema response
   format. In this no-send phase, tool arguments and action/workflow payloads
   are closed JSON objects to stay compatible with strict structured outputs;
   Fase 5 should introduce typed per-tool argument schemas for the tool loop.
3. Parses the raw JSON into `LLMAgentTurnOutput`.
4. Runs `RespondStyleTurnValidator`.
5. If validation returns a retry instruction and retry is enabled, sends one
   retry request with structured validator feedback.
6. Returns `FinalTurnDecision` with `send_decision="no_send"` in all cases.

## Prompt Contract

The system prompt requires the model to:

- act as the tenant-configured agent
- write concisely for WhatsApp
- answer the customer intent first when facts are available
- use only provided facts
- propose tool requests when facts require tools
- propose a matching tool request for exact requirements, prices, availability,
  catalog, documents, appointments, or status when a matching tool is available
- propose field updates with evidence
- propose workflow events only through allowed bindings
- avoid inventing prices, requirements, approval, availability, or policy
- avoid mentioning tools, JSON, policies, prompts, workflows, traces, or internals
- end with a concrete next step or question tied to the customer's last message
- avoid generic support filler
- return only JSON matching the supplied schema

## Validation

The provider uses `RespondStyleTurnValidator` after each LLM output. Validation
covers the Phase 3 hard rules, including:

- `final_message` existence
- internal leak blocking
- supported claims
- price claims requiring quote evidence/tooling
- requirement claims requiring requirements evidence/tooling
- field proposals requiring evidence and writable policies
- workflow proposals requiring enabled bindings
- action proposals requiring permission
- handoff proposals requiring policy support
- retry instructions for repairable failures
- fail-closed `no_send` when unrecoverable

## Retry Behavior

The provider allows at most one retry by default.

If the first validator result includes `retry_instruction`, the provider appends
structured validator feedback to the context and asks the model to repair the
turn. The retry output is validated again. The final decision remains no-send.

If provider execution, parsing, or retry execution fails, the provider returns a
blocked `FinalTurnDecision` with `send_decision="no_send"`.

## No-Live Safety

Confirmed by implementation scope and tests:

- no outbox writes
- no WhatsApp activation
- no SendAdapter call
- no real workflow execution
- no real action execution
- no `AgentService` integration
- no `ConversationRunner` dependency
- no `HumanResponseComposer` dependency
- no `StructuredRuntimeComposer` dependency
- no visible fallback generation
- no tenant or vertical hardcode

The runner also reports side effects as false for outbox, workflows, and actions.

## Tests

Command:

```powershell
$env:PYTHONPATH='core'; & 'core\.venv\Scripts\python.exe' -m pytest core/tests/agent_runtime/test_respond_style_turn_contract.py core/tests/agent_runtime/test_respond_style_turn_validator.py core/tests/agent_runtime/test_respond_style_llm_provider.py
```

Result:

- `32 passed in 0.29s`

Command:

```powershell
$env:PYTHONPATH='core'; & 'core\.venv\Scripts\python.exe' -m ruff check core/atendia/agent_runtime/respond_style_llm_provider.py core/tests/agent_runtime/test_respond_style_llm_provider.py tools/run_respond_style_llm_provider_no_send_2026_06_09.py
```

Result:

- `All checks passed`

## Manual OpenAI No-Send Runner

Command:

```powershell
$env:PYTHONPATH='core'; & 'core\.venv\Scripts\python.exe' tools/run_respond_style_llm_provider_no_send_2026_06_09.py
```

Result:

```json
{
  "decision": "RESPOND_STYLE_LLM_TURN_PROVIDER_READY",
  "mode": "no_send",
  "env_source": "core\\.env:ATENDIA_V2_OPENAI_API_KEY",
  "results": [
    {
      "scenario": "lead_new_greeting",
      "send_decision": "no_send",
      "validation_status": "valid",
      "side_effects": {
        "outbox": false,
        "workflows": false,
        "actions": false
      }
    },
    {
      "scenario": "lead_new_info",
      "send_decision": "no_send",
      "validation_status": "valid",
      "side_effects": {
        "outbox": false,
        "workflows": false,
        "actions": false
      }
    },
    {
      "scenario": "requirements_question",
      "send_decision": "no_send",
      "validation_status": "valid",
      "side_effects": {
        "outbox": false,
        "workflows": false,
        "actions": false
      }
    },
    {
      "scenario": "price_objection",
      "send_decision": "no_send",
      "validation_status": "valid",
      "side_effects": {
        "outbox": false,
        "workflows": false,
        "actions": false
      }
    }
  ]
}
```

OpenAI real execution was performed from `ATENDIA_V2_OPENAI_API_KEY` loaded via
`core/.env`. The runner did not print the secret and did not write outbox,
execute workflows, execute actions, call live SendAdapter, or activate WhatsApp.

Observed output summary:

- `hola`: valid no-send greeting.
- `busco info`: valid no-send clarification question.
- `que ocupo`: valid no-send clarification question; no tool executed.
- `esta caro`: valid no-send objection response.

Observation for Fase 5: the model remained conservative and did not propose the
requirements tool for the generic `que ocupo` scenario. This does not create a
live safety issue in Fase 4 because the provider is no-send and validates the
turn, but the tool-loop phase should add stronger typed tool-intent routing and
tool-result feedback.

Previous run before `.env` loading support:

```json
{
  "decision": "RESPOND_STYLE_LLM_TURN_PROVIDER_BLOCKED_BY_OPENAI",
  "reason": "OPENAI_API_KEY and ATENDIA_V2_OPENAI_API_KEY are not set",
  "side_effects": {
    "outbox": false,
    "workflows": false,
    "actions": false
  }
}
```

## Decision

`RESPOND_STYLE_LLM_TURN_PROVIDER_READY`

Reason: the provider uses the new Respond-Style Turn Contract, is prepared to
call OpenAI with strict JSON schema, validates every output with
`RespondStyleTurnValidator`, produces retry instructions for repairable
validator failures, and remains isolated from all live, outbox, workflow,
action, SendAdapter, ConversationRunner, and legacy composer paths. OpenAI real
runner execution completed in no-send mode using `ATENDIA_V2_OPENAI_API_KEY`
from `core/.env`.
