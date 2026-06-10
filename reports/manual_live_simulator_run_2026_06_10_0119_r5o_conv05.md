# Manual Live Simulator Run (no-send)

Run: 2026_06_10_0119_r5o_conv05
Agent: moto-credit-agent (version v1)
Tenant: manual-review-tenant
Mode: no_send | outbox=0 | side_effects=0

## Transcript

- C> hola
- A> ¡Hola! Soy tu asesor de motos a crédito. ¿En qué puedo ayudarte hoy?
- C> quiero la metro a crédito
- C> tengo 4 años trabajando por mi cuenta
- A> Perfecto, con 4 años de experiencia trabajando por tu cuenta, puedes acceder al **plan semanal estándar** para la moto Metro. El enganche es del 30% y los pagos son semanales. Si estás dado de alta en el SAT, podrías calificar para un enganche del 20%. ¿Te gustaría avanzar con este plan o necesitas más información?
- C> soy comerciante
- C> sí estoy dado de alta en SAT
- C> qué me pides
- A> Para avanzar con el crédito de la moto Metro, necesitarás:

- Identificación oficial vigente
- Comprobante de domicilio reciente
- Comprobante de ingresos de los últimos 3 meses (pueden ser estados de cuenta si no tienes recibos de nómina)

Si tienes alguna otra pregunta o necesitas más detalles, aquí estoy para ayudarte.
- C> cuánto queda

## Turns

- turn 1: send_decision=no_send, outbound=yes
- turn 2: send_decision=no_send, outbound=no, no_send_reason=claim_missing_source_ref
- turn 3: send_decision=no_send, outbound=yes
- turn 4: send_decision=no_send, outbound=no, no_send_reason=claim_missing_source_ref,claim_missing_source_ref
- turn 5: send_decision=no_send, outbound=no, no_send_reason=claim_missing_source_ref
- turn 6: send_decision=no_send, outbound=yes
- turn 7: send_decision=no_send, outbound=no, no_send_reason=llm_turn_provider_failed

## Failures

- turn 2: claim_missing_source_ref
- turn 4: claim_missing_source_ref,claim_missing_source_ref
- turn 5: claim_missing_source_ref
- turn 7: llm_turn_provider_failed

## Summary

```json
{
  "conversation_id": "manual-sim-0",
  "turns": 7,
  "simulated_outbound_count": 3,
  "blocked_turns": 4,
  "outbound_outbox_writes": 0,
  "side_effects": {
    "delivery": false,
    "workflows": false,
    "actions": false,
    "field_writes": false
  }
}
```
