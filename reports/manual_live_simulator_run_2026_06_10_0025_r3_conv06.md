# Manual Live Simulator Run (no-send)

Run: 2026_06_10_0025_r3_conv06
Agent: moto-credit-agent (version v1)
Tenant: manual-review-tenant
Mode: no_send | outbox=0 | side_effects=0

## Transcript

- C> hola
- A> ¡Hola! ¿En qué puedo ayudarte hoy con respecto a motos?
- C> busco una moto barata
- C> tengo 18 meses trabajando
- A> Perfecto, ya tengo tu antigüedad laboral de 18 meses. ¿Cómo recibes tus ingresos? (por nómina, transferencia, efectivo o negocio propio) Esto me ayudará a encontrar la mejor opción para ti.
- C> me pagan por transferencia
- A> Con 18 meses de antigüedad laboral y recibiendo tus ingresos por transferencia, puedes acceder al plan semanal estándar. Este plan requiere un enganche del 30%. Si estás interesado en saber más sobre las motos disponibles, ¿tienes algún modelo en mente o prefieres que te muestre algunas opciones económicas?
- C> me gusta la opción estándar
- A> Excelente elección con el plan estándar. Para continuar, necesitarás presentar los siguientes documentos:

1. Identificación oficial vigente.
2. Comprobante de domicilio reciente.
3. Comprobante de ingresos de los últimos 3 meses (los estados de cuenta sirven si no tienes recibos de nómina).

Si ya tienes en mente algún modelo de moto o necesitas ayuda para elegir, ¡dímelo!
- C> cuánto me queda
- A> Para poder darte el precio y enganche exactos, necesito saber qué modelo de moto te interesa. ¿Tienes algún modelo en mente o prefieres que te muestre algunas opciones?
- C> está muy caro
- A> Si prefieres hablar con un asesor humano para explorar opciones más económicas o resolver tus dudas, puedo pasarte con uno de ellos. ¿Te gustaría?
- C> hay una más barata?
- A> Si deseas, puedo pasarte con un asesor humano que te ayude a encontrar opciones más económicas. ¿Te gustaría hablar con uno?

## Turns

- turn 1: send_decision=no_send, outbound=yes
- turn 2: send_decision=no_send, outbound=no, no_send_reason=hard_policy_unsupported:requirements_require_support
- turn 3: send_decision=no_send, outbound=yes
- turn 4: send_decision=no_send, outbound=yes
- turn 5: send_decision=no_send, outbound=yes
- turn 6: send_decision=no_send, outbound=yes
- turn 7: send_decision=no_send, outbound=yes
- turn 8: send_decision=no_send, outbound=yes

## Failures

- turn 2: hard_policy_unsupported:requirements_require_support

## Summary

```json
{
  "conversation_id": "manual-sim-0",
  "turns": 8,
  "simulated_outbound_count": 7,
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
