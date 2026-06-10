# Manual Live Simulator Run (no-send)

Run: 2026_06_10_0026_r3_conv07
Agent: moto-credit-agent (version v1)
Tenant: manual-review-tenant
Mode: no_send | outbox=0 | side_effects=0

## Transcript

- C> hola
- A> ¡Hola! ¿En qué puedo ayudarte hoy con respecto a motos a crédito?
- C> qué ocupo
- A> Para poder decirte qué documentos necesitas, primero necesito saber cómo recibes tus ingresos. ¿Es por nómina, transferencia, efectivo o tienes un negocio propio?
- C> ya te dije que quiero crédito no?
- A> Sí, me mencionaste que quieres crédito. Para ayudarte mejor, necesito saber cómo recibes tus ingresos: ¿por nómina, transferencia, efectivo o tienes un negocio propio?
- C> tengo 15 meses
- A> Perfecto, tienes 15 meses de antigüedad laboral. Ahora, para poder ayudarte con el crédito, necesito saber cómo recibes tus ingresos: ¿por nómina, transferencia, efectivo o tienes un negocio propio?
- C> me pagan por fuera
- A> Con ingresos en efectivo y 15 meses de antigüedad laboral, puedes acceder a un plan semanal estándar. El enganche es del 30%. Si en algún momento te das de alta en el SAT, podrías acceder a un enganche del 20%. ¿Te gustaría saber más sobre los modelos de motos disponibles?
- C> entonces qué sigue
- C> eres robot?
- A> Sí, soy un asistente digital diseñado para ayudarte con la compra de motos a crédito. Si prefieres hablar con un asesor humano, puedo pasarte con uno. ¿Te gustaría eso?

## Turns

- turn 1: send_decision=no_send, outbound=yes
- turn 2: send_decision=no_send, outbound=yes
- turn 3: send_decision=no_send, outbound=yes
- turn 4: send_decision=no_send, outbound=yes
- turn 5: send_decision=no_send, outbound=yes
- turn 6: send_decision=no_send, outbound=no, no_send_reason=hard_policy_unsupported:price_or_down_payment_requires_support
- turn 7: send_decision=no_send, outbound=yes

## Failures

- turn 6: hard_policy_unsupported:price_or_down_payment_requires_support

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
