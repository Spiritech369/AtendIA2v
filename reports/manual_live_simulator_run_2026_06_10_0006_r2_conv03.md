# Manual Live Simulator Run (no-send)

Run: 2026_06_10_0006_r2_conv03
Agent: moto-credit-agent (version v1)
Tenant: manual-review-tenant
Mode: no_send | outbox=0 | side_effects=0

## Transcript

- C> hola
- A> ¡Hola! Soy tu asesor de motos. ¿En qué puedo ayudarte hoy?
- C> qué ocupo para sacar una moto
- C> pero dime los papeles primero
- C> tengo como 2 años trabajando
- A> Perfecto, gracias por compartir que tienes 2 años trabajando. ¿Cómo recibes tus ingresos? Puede ser por nómina, transferencia, efectivo o si tienes un negocio propio.
- C> me pagan por nómina
- A> Me dices que te pagan por nómina. Con esta información, puedo ayudarte mejor. Ahora, ¿estás dado de alta en el SAT? Esto puede abrir más opciones para tu plan de crédito.
- C> quiero una económica

## Turns

- turn 1: send_decision=no_send, outbound=yes
- turn 2: send_decision=no_send, outbound=no, no_send_reason=required_tool_skipped:missing_precondition:income_type
- turn 3: send_decision=no_send, outbound=no, no_send_reason=required_tool_skipped:missing_precondition:income_type
- turn 4: send_decision=no_send, outbound=yes
- turn 5: send_decision=no_send, outbound=yes
- turn 6: send_decision=no_send, outbound=no, no_send_reason=no_final_response_after_tools

## Failures

- turn 2: required_tool_skipped:missing_precondition:income_type
- turn 3: required_tool_skipped:missing_precondition:income_type
- turn 6: no_final_response_after_tools

## Summary

```json
{
  "conversation_id": "manual-sim-0",
  "turns": 6,
  "simulated_outbound_count": 3,
  "blocked_turns": 3,
  "outbound_outbox_writes": 0,
  "side_effects": {
    "delivery": false,
    "workflows": false,
    "actions": false,
    "field_writes": false
  }
}
```
