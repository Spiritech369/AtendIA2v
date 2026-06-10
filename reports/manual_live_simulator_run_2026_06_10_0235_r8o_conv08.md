# Manual Live Simulator Run (no-send)

Run: 2026_06_10_0235_r8o_conv08
Agent: moto-credit-agent (version v1)
Tenant: manual-review-tenant
Mode: no_send | outbox=0 | side_effects=0

## Transcript

- C> hola
- A> ¡Hola! Soy tu asesor de motos a crédito. ¿En qué puedo ayudarte hoy?
- C> quiero sacar una moto
- A> ¡Perfecto! Para ayudarte mejor, cuéntame un poco sobre tu antigüedad laboral. ¿Cuánto tiempo llevas trabajando en tu empleo actual?
- C> tengo 15 meses trabajando
- A> Gracias por compartirlo. Ahora, ¿cómo recibes tus ingresos? ¿Por nómina, transferencia, efectivo o tienes un negocio propio? Esto me ayudará a encontrar el plan de crédito adecuado para ti.
- C> no, perdón, tengo 10 meses
- A> Gracias por la corrección. Entonces, llevas 10 meses trabajando. Ahora, ¿cómo recibes tus ingresos? ¿Por nómina, transferencia, efectivo o tienes un negocio propio? Esto me ayudará a encontrar el plan de crédito adecuado para ti.
- C> me pagan por nómina
- A> Gracias por la información. Con 10 meses de antigüedad laboral y recibiendo ingresos por nómina, puedes acceder al plan de crédito semanal estándar. Este plan requiere un enganche del 30% y los pagos son semanales. Si tienes alguna otra pregunta o necesitas más detalles, estoy aquí para ayudarte. ¿Te gustaría saber más sobre algún modelo específico de moto?
- C> bueno, realmente me pagan por transferencia sin recibos
- A> Gracias por aclararlo. Con 10 meses de antigüedad laboral y recibiendo ingresos por transferencia sin recibos, puedes acceder al plan de crédito semanal estándar. Este plan requiere un enganche del 30% y los pagos son semanales. Si tienes alguna otra pregunta o necesitas más detalles sobre algún modelo específico de moto, estoy aquí para ayudarte.
- C> qué plan sería
- A> Con 10 meses de antigüedad laboral y recibiendo ingresos por transferencia sin recibos, puedes acceder al **plan semanal estándar**. Este plan requiere un enganche del 30% y los pagos son semanales. Si tienes más preguntas o necesitas detalles sobre algún modelo específico de moto, estoy aquí para ayudarte.

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
