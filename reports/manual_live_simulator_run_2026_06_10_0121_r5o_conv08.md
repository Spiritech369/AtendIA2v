# Manual Live Simulator Run (no-send)

Run: 2026_06_10_0121_r5o_conv08
Agent: moto-credit-agent (version v1)
Tenant: manual-review-tenant
Mode: no_send | outbox=0 | side_effects=0

## Transcript

- C> hola
- A> ¡Hola! Soy tu asesor de motos por WhatsApp. ¿En qué puedo ayudarte hoy?
- C> quiero sacar una moto
- C> tengo 15 meses trabajando
- C> no, perdón, tengo 10 meses
- C> me pagan por nómina
- C> bueno, realmente me pagan por transferencia sin recibos
- C> qué plan sería

## Turns

- turn 1: send_decision=no_send, outbound=yes
- turn 2: send_decision=no_send, outbound=no, no_send_reason=llm_turn_provider_failed
- turn 3: send_decision=no_send, outbound=no, no_send_reason=llm_turn_provider_failed
- turn 4: send_decision=no_send, outbound=no, no_send_reason=llm_turn_provider_failed
- turn 5: send_decision=no_send, outbound=no, no_send_reason=llm_turn_provider_failed
- turn 6: send_decision=no_send, outbound=no, no_send_reason=llm_turn_provider_failed
- turn 7: send_decision=no_send, outbound=no, no_send_reason=llm_turn_provider_failed

## Failures

- turn 2: llm_turn_provider_failed
- turn 3: llm_turn_provider_failed
- turn 4: llm_turn_provider_failed
- turn 5: llm_turn_provider_failed
- turn 6: llm_turn_provider_failed
- turn 7: llm_turn_provider_failed

## Summary

```json
{
  "conversation_id": "manual-sim-0",
  "turns": 7,
  "simulated_outbound_count": 1,
  "blocked_turns": 6,
  "outbound_outbox_writes": 0,
  "side_effects": {
    "delivery": false,
    "workflows": false,
    "actions": false,
    "field_writes": false
  }
}
```
