# Manual Live Simulator Run (no-send)

Run: 2026_06_09_2354_conv06_objecion_precio
Agent: moto-credit-agent (version v1)
Tenant: manual-review-tenant
Mode: no_send | outbox=0 | side_effects=0

## Transcript

- C> hola
- A> ¡Hola! ¿En qué puedo ayudarte hoy con respecto a las motos?
- C> busco una moto barata
- A> ¡Hola! Para ayudarte a encontrar una moto barata, primero necesito saber un poco más sobre ti. ¿Cuál es tu antigüedad laboral?
- C> tengo 18 meses trabajando
- A> Perfecto, tienes 18 meses trabajando. ¿Cómo recibes tus ingresos? ¿Es por nómina, transferencia, efectivo o tienes un negocio propio?
- C> me pagan por transferencia
- A> Recibes tus ingresos por transferencia. Con 18 meses de antigüedad laboral y este tipo de ingreso, puedes acceder a un plan de crédito estándar con un enganche del 30%. ¿Te gustaría saber más sobre los modelos de motos disponibles?
- C> me gusta la opción estándar
- A> Con el plan estándar, puedes acceder a un enganche del 30%. ¿Te gustaría que busque algunos modelos de motos que se ajusten a tu presupuesto?
- C> cuánto me queda
- A> Con el plan estándar, puedes acceder a un enganche del 30%. ¿Te gustaría que busque algunos modelos de motos que se ajusten a tu presupuesto?
- C> está muy caro
- C> hay una más barata?

## Turns

- turn 1: send_decision=no_send, outbound=yes
- turn 2: send_decision=no_send, outbound=yes
- turn 3: send_decision=no_send, outbound=yes
- turn 4: send_decision=no_send, outbound=yes
- turn 5: send_decision=no_send, outbound=yes
- turn 6: send_decision=no_send, outbound=yes
- turn 7: send_decision=no_send, outbound=no, no_send_reason=required_tool_skipped:missing_precondition:selected_model
- turn 8: send_decision=no_send, outbound=no, no_send_reason=required_tool_skipped:missing_precondition:selected_model

## Failures

- turn 7: required_tool_skipped:missing_precondition:selected_model
- turn 8: required_tool_skipped:missing_precondition:selected_model

## Summary

```json
{
  "conversation_id": "manual-sim-0",
  "turns": 8,
  "simulated_outbound_count": 6,
  "blocked_turns": 2,
  "outbound_outbox_writes": 0,
  "side_effects": {
    "delivery": false,
    "workflows": false,
    "actions": false,
    "field_writes": false
  }
}
```
