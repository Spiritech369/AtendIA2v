# Manual Live Simulator Run (no-send)

Run: 2026_06_10_0010_r2_conv08
Agent: moto-credit-agent (version v1)
Tenant: manual-review-tenant
Mode: no_send | outbox=0 | side_effects=0

## Transcript

- C> hola
- A> ¡Hola! Soy tu asesor de motos. ¿En qué puedo ayudarte hoy?
- C> quiero sacar una moto
- A> ¡Genial! Para ayudarte a sacar una moto, primero necesito saber tu antigüedad laboral. ¿Cuánto tiempo llevas trabajando?
- C> tengo 15 meses trabajando
- A> Perfecto, tienes 15 meses trabajando. Ahora, ¿cómo recibes tus ingresos? (por ejemplo, nómina, transferencia, efectivo o negocio propio) Esto me ayudará a encontrar el mejor plan de crédito para ti.
- C> no, perdón, tengo 10 meses
- A> Entiendo, tienes 10 meses trabajando. Ahora, ¿cómo recibes tus ingresos? (por ejemplo, nómina, transferencia, efectivo o negocio propio) Esto me ayudará a encontrar el mejor plan de crédito para ti.
- C> me pagan por nómina
- C> bueno, realmente me pagan por transferencia sin recibos
- A> Perfecto, tienes 10 meses trabajando y recibes tus ingresos por nómina. Para el plan de crédito, el enganche es del 30% y los pagos son semanales. Necesitarás presentar los siguientes documentos:
- Identificación oficial vigente
- Comprobante de domicilio reciente
- Comprobante de ingresos de los últimos 3 meses (estados de cuenta sirven si no hay recibos de nómina).

¿Tienes en mente algún modelo de moto que te gustaría considerar?
- C> qué plan sería
- A> Para el plan de crédito, el enganche es del 30% y los pagos son semanales. Necesitarás presentar los siguientes documentos:
- Identificación oficial vigente
- Comprobante de domicilio reciente
- Comprobante de ingresos de los últimos 3 meses (estados de cuenta sirven si no hay recibos de nómina).

¿Tienes en mente algún modelo de moto que te gustaría considerar?

## Turns

- turn 1: send_decision=no_send, outbound=yes
- turn 2: send_decision=no_send, outbound=yes
- turn 3: send_decision=no_send, outbound=yes
- turn 4: send_decision=no_send, outbound=yes
- turn 5: send_decision=no_send, outbound=no, no_send_reason=hard_policy_unsupported:requirements_require_support
- turn 6: send_decision=no_send, outbound=yes
- turn 7: send_decision=no_send, outbound=yes

## Failures

- turn 5: hard_policy_unsupported:requirements_require_support

## Summary

```json
{
  "conversation_id": "manual-sim-0",
  "turns": 7,
  "simulated_outbound_count": 6,
  "blocked_turns": 1,
  "outbound_outbox_writes": 0,
  "side_effects": {
    "delivery": false,
    "workflows": false,
    "actions": false,
    "field_writes": false
  }
}
```
