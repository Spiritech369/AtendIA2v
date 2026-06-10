# Respond-Style Shadow Runner No-Send - 2026-06-09

## Decision

`PHASE_6_RESPOND_STYLE_SHADOW_RUNNER_READY`

## Purpose

Phase 6 adds a no-live shadow runner that compares a current-path snapshot or
injected adapter against the new Respond-Style path. It produces structured
evidence without sending messages, writing live outbox rows, executing real
workflows/actions, or replacing AgentService or ConversationRunner.

## Architecture

```txt
AgentTurnInput + AgentContextPackage
-> current path adapter or snapshot
-> RespondStyleToolLoop
-> ShadowRunResult
-> copy-quality comparison
-> recommendation
```

The current path is not imported from legacy runtime. It is injected as
`CurrentPathShadowAdapter` or represented by a snapshot.

The Respond-Style path uses:

- `RespondStyleToolLoop`
- `RespondStyleLLMTurnProvider`
- dry/fact-only tool executor
- `RespondStyleTurnValidator`
- `FinalTurnDecision.send_decision="no_send"`

## Implemented Files

- `core/atendia/agent_runtime/respond_style_shadow_runner.py`
- `core/tests/agent_runtime/test_respond_style_shadow_runner.py`
- `tools/run_respond_style_shadow_runner_no_send_2026_06_09.py`
- `reports/respond_style_shadow_runner_no_send_2026_06_09.md`
- lazy exports in `core/atendia/agent_runtime/__init__.py`
- shadow runner rules in `docs/architecture/respond_style_runtime_implementation_plan.md`

## ShadowRunResult

The result includes:

- run id
- tenant id
- agent id
- conversation id
- input summary
- current path final message, tools, field updates, validation result
- Respond-Style final message, tools, tool results, field updates, workflow
  events, validation result, retry instruction, send decision
- comparison scores and recommendation
- final decision `no_send`
- side-effect flags

## Copy Comparison

The comparison scores both outputs from 1 to 5 on:

- naturalness
- response to user intent
- continuity
- commercial progress
- not form-like
- no internal language
- supported facts
- WhatsApp brevity

It also flags:

- internal leaks
- generic/legacy-like copy
- whether Respond-Style responds to intent better
- whether Respond-Style is less robotic
- whether facts are supported

Recommendations are:

- `prefer_respond_style`
- `prefer_current_path`
- `needs_review`

## Tests

Command:

```powershell
$env:PYTHONPATH='core'; & 'core\.venv\Scripts\python.exe' -m pytest core/tests/agent_runtime/test_respond_style_turn_contract.py core/tests/agent_runtime/test_respond_style_turn_validator.py core/tests/agent_runtime/test_respond_style_llm_provider.py core/tests/agent_runtime/test_respond_style_tool_loop.py core/tests/agent_runtime/test_respond_style_shadow_runner.py
```

Result:

- `57 passed in 0.36s`

Command:

```powershell
$env:PYTHONPATH='core'; & 'core\.venv\Scripts\python.exe' -m ruff check core/atendia/agent_runtime/respond_style_llm_provider.py core/atendia/agent_runtime/respond_style_tool_loop.py core/atendia/agent_runtime/respond_style_shadow_runner.py core/tests/agent_runtime/test_respond_style_llm_provider.py core/tests/agent_runtime/test_respond_style_tool_loop.py core/tests/agent_runtime/test_respond_style_shadow_runner.py tools/run_respond_style_shadow_runner_no_send_2026_06_09.py
```

Result:

- `All checks passed`

Coverage added for:

- shadow runner executes both injected paths
- shadow runner forces no-send
- shadow runner works when current path is unavailable
- comparison detects internal leaks
- comparison detects generic/legacy-like copy
- comparison prefers Respond-Style when it has supported facts and stronger
  intent response
- shadow result records tool results and validator decisions
- shadow runner source has no unsafe live/legacy imports
- shadow runner source has no tenant/vertical hardcodes

## OpenAI No-Send Runner

Command:

```powershell
$env:PYTHONPATH='core'; & 'core\.venv\Scripts\python.exe' tools/run_respond_style_shadow_runner_no_send_2026_06_09.py
```

Result:

- decision: `PHASE_6_RESPOND_STYLE_SHADOW_RUNNER_READY`
- mode: `no_send`
- key source: `core\.env:ATENDIA_V2_OPENAI_API_KEY`
- side effects: `outbox=false`, `workflows=false`, `actions=false`

Scenario summary:

| Scenario | Current Score | Respond-Style Score | Tools | Recommendation |
| --- | ---: | ---: | --- | --- |
| greeting | 31 | 36 | none | prefer_respond_style |
| info | 29 | 35 | none | prefer_respond_style |
| seniority | 31 | 36 | none | prefer_respond_style |
| requirements | 28 | 33 | requirements.lookup succeeded | prefer_respond_style |
| merchant | 28 | 36 | none | prefer_respond_style |
| price_objection | 29 | 34 | alternate_product_search succeeded | prefer_respond_style |
| robot | 31 | 35 | none | prefer_respond_style |
| model | 31 | 21 | blocked no-send | prefer_current_path |
| chaotic | 29 | 35 | requirements.lookup succeeded | prefer_respond_style |

Important observation:

- The `model` scenario caused Respond-Style to fail closed with no customer copy
  because validation blocked unsupported requirements-style content. This is
  acceptable in Phase 6 because shadow is no-send and the purpose is evidence.
  Phase 7 should use this as a context/tool-intent gap to address before direct
  runtime integration.

## No-Live Safety

Confirmed:

- no WhatsApp activation
- no smoke activation
- no live outbox write
- no live SendAdapter
- no AgentService replacement
- no ConversationRunner dependency
- no HumanResponseComposer dependency in the new route
- no StructuredRuntimeComposer dependency
- no real workflow execution
- no real action execution
- no worktree cleanup

## Recommendation For Phase 7

Proceed to Phase 7 only as a direct ProductAgentRuntime path in no-send or
shadow mode. The shadow result supports using Respond-Style as the candidate
path, but the direct path must keep the same fail-closed behavior observed here:
unsupported facts, missing tools, or skipped required tools stay `no_send`.
