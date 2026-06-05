# Eval Lab v1

Eval Lab v1 is a deterministic backend harness for AgentRuntime v2. It runs safe test scenarios, captures `TurnOutput`, and scores the output without sending messages, mutating contacts, moving lifecycle, or executing workflows/actions.

## Files

- `core/atendia/eval_lab/schemas.py`: scenario and result contracts.
- `core/atendia/eval_lab/scenario_runner.py`: builds simulated context and runs `AgentRuntime`.
- `core/atendia/eval_lab/scorers.py`: deterministic score functions.
- `core/atendia/eval_lab/fixtures.py`: generic scenarios, blueprint scenarios, and a fixture provider.
- `core/atendia/eval_lab/run_scenarios.py`: CLI entrypoint.

## Scenario Shape

Each scenario includes:

- `id`, `name`, optional `vertical`
- `input_message`
- optional `conversation_history`
- optional `contact_fields`
- optional `lifecycle_stage`
- optional `knowledge_sources`
- `expected_behaviors`
- `forbidden_behaviors`
- optional expected field updates, lifecycle target, and action names

The runner maps this into a simulated `TurnContext`; it does not use production conversations.

## Scorers

Initial deterministic scorers:

- `answered_current_question`
- `asked_at_most_one_question`
- `did_not_emit_empty_response`
- `no_unknown_actions`
- `field_updates_have_evidence`
- `lifecycle_has_reason`
- `no_multiple_final_messages`
- `confidence_valid`
- `no_forbidden_phrases`
- `needs_human_when_low_confidence`

There is no LLM judge in v1. That can be added later as an optional scorer, not as the default gate.

## Scenario Fixtures

Generic scenarios cover:

- price question
- appointment request
- human handoff request
- budget data capture
- hours question
- correction/contradiction of prior data
- knowledge gap
- short replies: `sí`, `esa`, `mañana`

Blueprint fixtures are included for:

- `automotive/motos`
- `automotive/autos`
- `inmuebles`
- `dental/clinics`
- `beauty/barber/spa`

These are scenario examples only. They do not add vertical logic to AgentRuntime.

## How To Run

From `core/`:

```bash
python -m atendia.eval_lab.run_scenarios
python -m atendia.eval_lab.run_scenarios --include-blueprints
python -m atendia.eval_lab.run_scenarios --include-blueprints --json
```

The CLI uses `FixtureAgentProvider` by default so the harness can be validated before a real LLM/provider is connected. Production or CI evals should pass a runtime/provider factory to `ScenarioRunner`.

## Safety

The harness only calls `AgentRuntime.run_turn`. It never calls `PostTurnActionExecutor`, WhatsApp, outbox, lifecycle services, contact-memory writers, or workflows.

## Pending

- Scenario file loader from YAML/JSON.
- Regression baseline storage.
- Optional LLM judge for nuanced criteria.
- Eval API endpoint and frontend Eval Lab UI.
- Knowledge fixture generation from Knowledge OS source cards.
