# Manual Live Simulator Run (no-send)

Run: 2026_06_10_0011_r2_conv09
Agent: moto-credit-agent (version v1)
Tenant: manual-review-tenant
Mode: no_send | outbox=0 | side_effects=0

## Transcript

- C> hola
- A> ¡Hola! Soy tu asesor de motos. ¿En qué puedo ayudarte hoy?
- C> quiero una moto a crédito
- A> ¡Genial! Para ayudarte a obtener una moto a crédito, primero necesito saber tu antigüedad laboral. ¿Cuánto tiempo llevas trabajando?
- C> tengo 2 años trabajando
- A> Perfecto, tienes 2 años trabajando. ¿Cómo recibes tus ingresos? (por nómina, transferencia, efectivo o negocio propio)
- C> me pagan por transferencia
- A> Perfecto, me mencionas que recibes tus ingresos por transferencia. Con 2 años de antigüedad laboral y este tipo de ingreso, puedes acceder a un plan de crédito estándar con un enganche del 30%. ¿Te gustaría saber más sobre los modelos de motos disponibles?
- C> quiero la roja que vi en el anuncio
- A> Con 2 años de antigüedad laboral y recibiendo ingresos por transferencia, puedes acceder a un plan de crédito estándar. ¿Te gustaría saber más sobre los modelos de motos disponibles? Te puedo ayudar a elegir la roja que viste en el anuncio.
- C> no sé el nombre
- C> algo económico para moverme al trabajo
- C> qué opciones hay

## Turns

- turn 1: send_decision=no_send, outbound=yes
- turn 2: send_decision=no_send, outbound=yes
- turn 3: send_decision=no_send, outbound=yes
- turn 4: send_decision=no_send, outbound=yes
- turn 5: send_decision=no_send, outbound=yes
- turn 6: send_decision=no_send, outbound=no, no_send_reason=no_final_response_after_tools
- turn 7: send_decision=no_send, outbound=no, no_send_reason=no_final_response_after_tools
- turn 8: send_decision=no_send, outbound=no, no_send_reason=no_final_response_after_tools

## Failures

- turn 6: no_final_response_after_tools
- turn 7: no_final_response_after_tools
- turn 8: no_final_response_after_tools

## Summary

```json
{
  "conversation_id": "manual-sim-0",
  "turns": 8,
  "simulated_outbound_count": 5,
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
