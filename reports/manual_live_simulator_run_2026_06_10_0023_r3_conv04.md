# Manual Live Simulator Run (no-send)

Run: 2026_06_10_0023_r3_conv04
Agent: moto-credit-agent (version v1)
Tenant: manual-review-tenant
Mode: no_send | outbox=0 | side_effects=0

## Transcript

- C> buenas
- A> ¡Hola! ¿En qué puedo ayudarte hoy?
- C> quiero crédito para una moto
- A> ¡Claro! Para poder ayudarte con el crédito, necesito saber cómo recibes tus ingresos. ¿Es por nómina, transferencia, efectivo o tienes un negocio propio?
- C> tengo negocio
- A> Perfecto, tienes un negocio. Ahora, necesito saber tu antigüedad laboral, es decir, cuánto tiempo llevas trabajando en tu negocio. ¿Me puedes decir eso?
- C> vendo comida desde mi casa
- A> ¡Eso suena genial! Solo necesito saber cuánto tiempo llevas vendiendo comida desde tu casa para poder avanzar con el crédito. ¿Me puedes decir tu antigüedad laboral?
- C> tengo 3 años con el negocio
- A> Con 3 años de antigüedad en tu negocio, puedes acceder a un plan de crédito semanal estándar. El enganche es del 30%. Si estás dado de alta en el SAT, podrías acceder a un enganche del 20%. ¿Te gustaría saber más sobre los modelos de motos disponibles?
- C> qué papeles ocupo
- A> Para el crédito de la moto, necesitas presentar los siguientes documentos:

1. Identificación oficial vigente.
2. Comprobante de domicilio reciente.
3. Comprobante de ingresos de los últimos 3 meses (pueden ser estados de cuenta si no tienes recibos de nómina).

¿Te gustaría ver algunos modelos de motos disponibles?
- C> cuánto tendría que dar

## Turns

- turn 1: send_decision=no_send, outbound=yes
- turn 2: send_decision=no_send, outbound=yes
- turn 3: send_decision=no_send, outbound=yes
- turn 4: send_decision=no_send, outbound=yes
- turn 5: send_decision=no_send, outbound=yes
- turn 6: send_decision=no_send, outbound=yes
- turn 7: send_decision=no_send, outbound=no, no_send_reason=required_tool_skipped:missing_precondition:selected_model

## Failures

- turn 7: required_tool_skipped:missing_precondition:selected_model

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
