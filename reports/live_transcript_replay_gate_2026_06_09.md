# LIVE_TRANSCRIPT_REPLAY_GATE - 2026-06-09

## Decision

`LIVE_TRANSCRIPT_REPLAY_GATE_PASSED_READY_FOR_APPROVAL_PACKET`

This was executed as DB-backed Runtime V2 AgentService `no_send` replay using the real failed WhatsApp transcript. No live send, smoke, outbox live, actions, workflow side effects, canary, or production opening were activated.

## Safety Status

- Runtime mode: `runtime_v2_live_transcript_replay_gate_no_send`
- Backend flags: `send=false`, `actions=false`, `workflow_events=false`
- Worker flags: `send=false`, `actions=false`, `workflow_events=false`
- Tenant flags: `send_enabled=false`, `outbox_enabled=false`, `live_send_enabled=false`, `single_contact_smoke_enabled=false`
- Tenant side-effect flags: `actions_enabled=false`, `workflow_events_enabled=false`, `workflow_side_effects_enabled=false`
- Tenant rollout flags: `canary_enabled=false`, `open_production_enabled=false`
- Tenant fallback flags: `legacy_fallback_enabled=false`, `provider_visible_fallback_enabled=false`, `manual_recovery_visible_enabled=false`
- DB audit after replay: `outbound_outbox pending/retry = 0`, `business_event_ledger side_effects_allowed = 0`

## Replay Result

- Suite ID: `5046f823-44c4-4182-b925-5a53c5c09e67`
- Test run ID: `231be8b6-9314-4ea4-8355-695c96826111`
- Run status: `passed`
- Run decision: `TEST_LAB_PASSED`
- Gate audit: `passed`
- Scenario turns: `18`
- Tenant: `6ad78236-1fc9-467a-858d-90d248d57ee5`
- Agent: `c169deec-226d-55b7-bd07-270f339e75a6`

## What Changed

- Explicit labor durations such as `15 meses`, `22 años`, and `tengo 10 meses` are treated as `employment_seniority`, even if the previous pending slot was income.
- `credit_plan.resolve` is not invoked for seniority-only answers.
- `business_tax_status` is not treated as consumed while the income interpretation still needs clarification.
- Pending fiscal status only invokes income resolution when the user provides evidence from the tenant contract, such as SAT/RIF or sin comprobantes signals.
- Generic connector turns such as `Entonces` and `Dime` are not consumed as income answers.
- `PolicyValidator` and the replay gate now block visible generic human-review filler such as `Necesito que una persona del equipo revise esto...`.
- If a policy block occurs but the validated response plan has a safe pending-slot question, the final visible message is repaired to that validated question instead of a generic fallback.

## Transcript Evidence

| Turn | Inbound | Final message | Tools | State writes |
|---:|---|---|---|---|
| 1 | Hola | ¡Hola! Para continuar, ¿cuánto tiempo llevas trabajando? | - | - |
| 2 | Busco info | ¿Cuánto tiempo llevas trabajando en tu empleo actual? | - | - |
| 3 | 15 meses | ¿Cómo recibes tus ingresos? | - | `cumple_antiguedad`, `employment_seniority` |
| 4 | hola | ¡Hola! Espero que estés bien. Para continuar, ¿podrías decirme cómo recibes tus ingresos? | - | - |
| 5 | que ocupo_ | ¿Cómo recibes tus ingresos? | - | - |
| 6 | 22 años | ¿Cómo recibes tus ingresos? | - | `cumple_antiguedad`, `employment_seniority` |
| 7 | hola | ¡Hola! Espero que estés bien. Para continuar, ¿podrías decirme cómo recibes tus ingresos? | - | - |
| 8 | ya te dije no? | Entiendo tu frustración. Aún necesitamos saber cómo recibes tus ingresos para avanzar. ¿Podrías decirme eso? | - | - |
| 9 | tengo 10 meses | ¿Cómo recibes tus ingresos? | - | `cumple_antiguedad`, `employment_seniority` |
| 10 | metro | Para continuar, ¿cómo recibes tus ingresos? | `catalog.search` | `product_catalog_id`, `product_selection` |
| 11 | si quiero saber | Para continuar, ¿podrías decirme cómo recibes tus ingresos? | - | - |
| 12 | que ocupo | Para continuar, ¿podrías decirme cómo recibes tus ingresos? | - | - |
| 13 | Entonces | Para continuar, ¿podrías decirme cómo recibes tus ingresos? | - | - |
| 14 | Soy comerciante | Para continuar, ¿tienes SAT/RIF o sería sin comprobantes? | `credit_plan.resolve` | - |
| 15 | Esta muy caro | ¿Tienes un SAT/RIF o sería sin comprobantes? | - | - |
| 16 | Que ocupas | ¿Tienes tu número de SAT/RIF o sería sin comprobantes? | - | - |
| 17 | Dime | ¿Tienes un número de SAT/RIF o sería sin comprobantes? | - | - |
| 18 | Eres un robot? | si tienes SAT/RIF o si seria sin comprobantes? | - | - |

## Verification

- `uv run ruff check atendia\agent_runtime\advisor_pipeline.py atendia\agent_runtime\policy_validator.py atendia\agent_runtime\live_transcript_replay_gate.py ..\tools\run_live_transcript_replay_gate_2026_06_09.py`
  - Result: passed.
- `uv run pytest tests\agent_runtime\test_live_transcript_replay_gate.py tests\agent_runtime\test_validated_response_plan_builder.py tests\agent_runtime\test_human_response_composer.py tests\agent_runtime\test_semantic_interpreter_runtime_v2.py -q`
  - Result: `78 passed`.
- `docker compose exec -T backend uv run pytest tests/agent_runtime/test_live_transcript_replay_gate.py tests/agent_runtime/test_validated_response_plan_builder.py tests/agent_runtime/test_human_response_composer.py tests/agent_runtime/test_semantic_interpreter_runtime_v2.py -q`
  - Result: `78 passed`.
- `uv run python ..\tools\run_live_transcript_replay_gate_2026_06_09.py`
  - Result: `LIVE_TRANSCRIPT_REPLAY_GATE_PASSED_READY_FOR_APPROVAL_PACKET`.

## Remaining Risk

The gate is now safe from the specific failed transcript class: no false tool execution for non-answers, no state drift on labor seniority, no generic human-review filler, no live send, no outbox, and no side effects. Some messages are still terse and repetitive, so the next approval packet should treat copy quality as a smoke criterion rather than assuming production readiness.
