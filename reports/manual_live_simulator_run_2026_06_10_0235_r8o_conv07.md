# Manual Live Simulator Run (no-send)

Run: 2026_06_10_0235_r8o_conv07
Agent: moto-credit-agent (version v1)
Tenant: manual-review-tenant
Mode: no_send | outbox=0 | side_effects=0

## Transcript

- C> hola
- A> ¡Hola! Soy tu asesor de motos a crédito. ¿En qué puedo ayudarte hoy?
- C> qué ocupo
- A> Para un crédito de moto, generalmente necesitas una identificación oficial vigente, un comprobante de domicilio reciente y alguna forma de demostrar tus ingresos. La lista exacta de documentos depende de cómo recibes tus ingresos y del plan específico.

¿Podrías contarme cómo recibes tus ingresos para darte más detalles?
- C> ya te dije que quiero crédito no?
- C> tengo 15 meses
- A> Perfecto, con 15 meses de antigüedad laboral ya cumples con uno de los requisitos. Ahora, para darte información más precisa sobre el crédito, ¿cómo recibes tus ingresos? Puede ser por nómina, transferencia, en efectivo o si tienes un negocio propio.
- C> me pagan por fuera
- A> Gracias por aclararlo. Para un crédito de moto, necesitarás:

- Identificación oficial vigente
- Comprobante de domicilio reciente
- Comprobante de ingresos de los últimos 3 meses (pueden ser estados de cuenta si no tienes recibos de nómina)

Si tienes alguna otra pregunta o necesitas más ayuda, aquí estoy para apoyarte. 😊
- C> entonces qué sigue
- A> Con tus 15 meses de antigüedad laboral y recibiendo ingresos por fuera de nómina, puedes acceder al plan semanal estándar. Este plan requiere un enganche del 30% y los pagos son semanales.

Si tienes un negocio propio y estás dado de alta en el SAT, podrías calificar para un enganche del 20%.

¿Te gustaría saber el precio de alguna moto en particular o necesitas más información sobre el proceso?
- C> eres robot?
- A> Soy un asistente digital aquí para ayudarte con información sobre motos a crédito. Si prefieres hablar con un asesor humano, puedo conectarte con alguien del equipo de ventas. ¿Te gustaría que lo haga?

## Turns

- turn 1: send_decision=no_send, outbound=yes
- turn 2: send_decision=no_send, outbound=yes
- turn 3: send_decision=no_send, outbound=no, no_send_reason=claim_missing_source_ref,claim_missing_source_ref
- turn 4: send_decision=no_send, outbound=yes
- turn 5: send_decision=no_send, outbound=yes
- turn 6: send_decision=no_send, outbound=yes
- turn 7: send_decision=no_send, outbound=yes

## Failures

- turn 3: claim_missing_source_ref,claim_missing_source_ref

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
