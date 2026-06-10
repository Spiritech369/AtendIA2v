# Manual Live Simulator Run (no-send)

Run: 2026_06_10_0214_r7o_conv03
Agent: moto-credit-agent (version v1)
Tenant: manual-review-tenant
Mode: no_send | outbox=0 | side_effects=0

## Transcript

- C> hola
- A> ¡Hola! Soy tu asesor de motos a crédito. ¿En qué puedo ayudarte hoy?
- C> qué ocupo para sacar una moto
- A> Para sacar una moto a crédito, en general necesitas una identificación oficial vigente, un comprobante de domicilio reciente y alguna forma de demostrar tus ingresos. La lista exacta de documentos depende de cómo recibes tus ingresos y se confirma con el sistema de verificación. Si me cuentas un poco más sobre cómo recibes tus ingresos, puedo darte detalles más precisos. 

Fuente: kb:general_credit_requirements
- C> pero dime los papeles primero
- A> Claro, en general necesitas una identificación oficial vigente, un comprobante de domicilio reciente y alguna forma de demostrar tus ingresos. La lista exacta de documentos depende de cómo recibes tus ingresos y se confirma con el sistema de verificación. Si me cuentas un poco más sobre cómo recibes tus ingresos, puedo darte detalles más precisos.

Fuente: kb:general_credit_requirements
- C> tengo como 2 años trabajando
- A> Perfecto, con 2 años de antigüedad laboral ya tienes un buen punto de partida. Ahora, ¿cómo recibes tus ingresos? Esto me ayudará a darte información más precisa sobre los documentos que necesitas.
- C> me pagan por nómina
- A> Perfecto, como recibes tus ingresos por nómina, los documentos que necesitas son:

- Identificación oficial vigente
- Comprobante de domicilio reciente
- Comprobante de ingresos de los últimos 3 meses (pueden ser estados de cuenta si no tienes recibos de nómina)

Con estos documentos, ya puedes avanzar en el proceso de crédito para tu moto. Si tienes alguna otra pregunta o necesitas más ayuda, aquí estoy.
- C> quiero una económica

## Turns

- turn 1: send_decision=no_send, outbound=yes
- turn 2: send_decision=no_send, outbound=yes
- turn 3: send_decision=no_send, outbound=yes
- turn 4: send_decision=no_send, outbound=yes
- turn 5: send_decision=no_send, outbound=yes
- turn 6: send_decision=no_send, outbound=no, no_send_reason=llm_turn_provider_retry_failed

## Failures

- turn 6: llm_turn_provider_retry_failed

## Summary

```json
{
  "conversation_id": "manual-sim-0",
  "turns": 6,
  "simulated_outbound_count": 5,
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
