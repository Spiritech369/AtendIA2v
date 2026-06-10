# Manual Live Simulator Run (no-send)

Run: 2026_06_10_0154_r6o_conv07
Agent: moto-credit-agent (version v1)
Tenant: manual-review-tenant
Mode: no_send | outbox=0 | side_effects=0

## Transcript

- C> hola
- A> ¡Hola! Soy tu asesor de motos a crédito. ¿En qué puedo ayudarte hoy?
- C> qué ocupo
- C> ya te dije que quiero crédito no?
- A> Sí, claro. Para ayudarte con el crédito, necesito saber un poco más sobre tu situación laboral. ¿Cuánto tiempo llevas trabajando en tu empleo actual?
- C> tengo 15 meses
- A> Perfecto, con 15 meses de antigüedad laboral ya podemos avanzar. Ahora, ¿cómo recibes tus ingresos? ¿Por nómina, transferencia, efectivo o tienes un negocio propio?
- C> me pagan por fuera
- A> Con 15 meses de antigüedad y recibiendo ingresos por fuera, calificas para el **plan semanal estándar**. Este plan requiere un enganche del 30% y los pagos son semanales. Si tienes un negocio propio y estás dado de alta en el SAT, podrías acceder a un enganche del 20%. 

¿Te gustaría saber más sobre algún modelo en particular o necesitas ayuda con otra cosa?
- C> entonces qué sigue
- A> Para avanzar con el crédito, necesitarás los siguientes documentos:

- Identificación oficial vigente
- Comprobante de domicilio reciente
- Comprobante de ingresos de los últimos 3 meses (pueden ser estados de cuenta si no tienes recibos de nómina)

Si tienes alguna otra pregunta o necesitas ayuda con un modelo específico, avísame.
- C> eres robot?
- A> Soy un asistente digital aquí para ayudarte con tus preguntas sobre motos a crédito. Si prefieres hablar con un asesor humano, puedo conectarte con alguien del equipo de ventas. ¿Te gustaría que lo haga?

## Turns

- turn 1: send_decision=no_send, outbound=yes
- turn 2: send_decision=no_send, outbound=no, no_send_reason=hard_policy_unsupported:requirements_require_support
- turn 3: send_decision=no_send, outbound=yes
- turn 4: send_decision=no_send, outbound=yes
- turn 5: send_decision=no_send, outbound=yes
- turn 6: send_decision=no_send, outbound=yes
- turn 7: send_decision=no_send, outbound=yes

## Failures

- turn 2: hard_policy_unsupported:requirements_require_support

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
