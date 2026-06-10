# Manual Live Simulator Run (no-send)

Run: 2026_06_09_2351_conv01_flujo_normal
Agent: moto-credit-agent (version v1)
Tenant: manual-review-tenant
Mode: no_send | outbox=0 | side_effects=0

## Transcript

- C> hola
- A> ¡Hola! ¿En qué puedo ayudarte hoy con respecto a las motos?
- C> busco una moto a crédito
- A> ¡Genial! Para ayudarte a encontrar la moto a crédito, primero necesito saber un par de cosas. ¿Cuál es tu antigüedad laboral?
- C> tengo 15 meses trabajando
- A> Perfecto, tienes 15 meses trabajando. ¿Cómo recibes tus ingresos? ¿Es por nómina, transferencia, efectivo o negocio propio?
- C> me pagan por transferencia
- A> Recibí que te pagan por transferencia. Con 15 meses de antigüedad laboral y este tipo de ingreso, puedes acceder a un plan de crédito estándar. ¿Te gustaría que revisemos opciones de motos ahora?
- C> no me dan nomina
- A> Con 15 meses de antigüedad laboral y recibiendo ingresos por transferencia, puedes acceder a un plan de crédito estándar. ¿Te gustaría que revisemos opciones de motos ahora?
- C> me interesa la DNM2.5
- A> Con 15 meses de antigüedad laboral y recibiendo ingresos por transferencia, puedes acceder a un plan de crédito estándar. La moto DNM2.5 está disponible. ¿Te gustaría que revisemos los requisitos para el crédito?
- C> qué ocupo para avanzar
- C> cuánto doy de enganche?

## Turns

- turn 1: send_decision=no_send, outbound=yes
- turn 2: send_decision=no_send, outbound=yes
- turn 3: send_decision=no_send, outbound=yes
- turn 4: send_decision=no_send, outbound=yes
- turn 5: send_decision=no_send, outbound=yes
- turn 6: send_decision=no_send, outbound=yes
- turn 7: send_decision=no_send, outbound=no
- turn 8: send_decision=no_send, outbound=no

## Summary

```json
{
  "conversation_id": "manual-sim-0",
  "turns": 8,
  "simulated_outbound_count": 6,
  "blocked_turns": 0,
  "outbound_outbox_writes": 0,
  "side_effects": {
    "delivery": false,
    "workflows": false,
    "actions": false,
    "field_writes": false
  }
}
```
