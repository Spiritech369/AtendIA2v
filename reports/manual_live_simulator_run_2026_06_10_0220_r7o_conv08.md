# Manual Live Simulator Run (no-send)

Run: 2026_06_10_0220_r7o_conv08
Agent: moto-credit-agent (version v1)
Tenant: manual-review-tenant
Mode: no_send | outbox=0 | side_effects=0

## Transcript

- C> hola
- A> ¡Hola! Soy tu asesor de motos a crédito. ¿En qué puedo ayudarte hoy?
- C> quiero sacar una moto
- A> ¡Genial! Para ayudarte mejor, cuéntame un poco sobre tu antigüedad laboral. ¿Cuánto tiempo llevas trabajando en tu empleo actual?
- C> tengo 15 meses trabajando
- A> Perfecto, gracias por compartirlo. Ahora, ¿cómo recibes tus ingresos? ¿Por nómina, transferencia, en efectivo o tienes un negocio propio? Esto me ayudará a encontrar el plan de crédito adecuado para ti.
- C> no, perdón, tengo 10 meses
- A> Gracias por la corrección. Entonces, con 10 meses de antigüedad laboral, ¿cómo recibes tus ingresos? ¿Por nómina, transferencia, en efectivo o tienes un negocio propio? Esto me ayudará a encontrar el plan de crédito adecuado para ti.
- C> me pagan por nómina
- A> Con 10 meses de antigüedad laboral y recibiendo ingresos por nómina, calificas para un plan de crédito semanal estándar. Este plan requiere un enganche del 30% y los pagos son semanales.

Si tienes alguna moto en mente o necesitas más información, ¡dime y te ayudo a buscarla!
- C> bueno, realmente me pagan por transferencia sin recibos
- A> Gracias por aclararlo. Con 10 meses de antigüedad laboral y recibiendo ingresos por transferencia sin recibos, calificas para un plan de crédito semanal estándar. Este plan requiere un enganche del 30% y los pagos son semanales.

Si tienes alguna moto en mente o necesitas más información, ¡dime y te ayudo a buscarla!
- C> qué plan sería
- A> Con 10 meses de antigüedad laboral y recibiendo ingresos por transferencia sin recibos, calificas para un **plan semanal estándar**. Este plan requiere un enganche del 30% y los pagos son semanales. 

Si tienes alguna moto en mente o necesitas más información, ¡dime y te ayudo a buscarla!

## Turns

- turn 1: send_decision=no_send, outbound=yes
- turn 2: send_decision=no_send, outbound=yes
- turn 3: send_decision=no_send, outbound=yes
- turn 4: send_decision=no_send, outbound=yes
- turn 5: send_decision=no_send, outbound=yes
- turn 6: send_decision=no_send, outbound=yes
- turn 7: send_decision=no_send, outbound=yes

## Summary

```json
{
  "conversation_id": "manual-sim-0",
  "turns": 7,
  "simulated_outbound_count": 7,
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
