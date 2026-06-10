# Manual Live Simulator Run (no-send)

Run: 2026_06_09_2353_conv03_requisitos_primero
Agent: moto-credit-agent (version v1)
Tenant: manual-review-tenant
Mode: no_send | outbox=0 | side_effects=0

## Transcript

- C> hola
- A> ¡Hola! ¿En qué puedo ayudarte hoy con respecto a las motos? Si estás interesado en un crédito, podemos empezar por saber tu antigüedad laboral.
- C> qué ocupo para sacar una moto
- C> pero dime los papeles primero
- C> tengo como 2 años trabajando
- A> Perfecto, tienes 2 años trabajando. Ahora, ¿cómo recibes tus ingresos? ¿Es por nómina, transferencia, efectivo o tienes un negocio propio?
- C> me pagan por nómina
- C> quiero una económica
- A> Para sacar una moto, necesitas los siguientes papeles:
- Identificación oficial vigente
- Comprobante de domicilio reciente
- Comprobante de ingresos de los últimos 3 meses (estados de cuenta sirven si no hay recibos de nómina).

Con 2 años de antigüedad y recibiendo ingresos por nómina, puedes acceder a un plan de crédito estándar. ¿Te gustaría saber más sobre los modelos disponibles o algún otro detalle?

## Turns

- turn 1: send_decision=no_send, outbound=yes
- turn 2: send_decision=no_send, outbound=no, no_send_reason=required_tool_skipped:missing_precondition:income_type
- turn 3: send_decision=no_send, outbound=no, no_send_reason=required_tool_skipped:missing_precondition:income_type
- turn 4: send_decision=no_send, outbound=yes
- turn 5: send_decision=no_send, outbound=no, no_send_reason=hard_policy_unsupported:requirements_require_support
- turn 6: send_decision=no_send, outbound=yes

## Failures

- turn 2: required_tool_skipped:missing_precondition:income_type
- turn 3: required_tool_skipped:missing_precondition:income_type
- turn 5: hard_policy_unsupported:requirements_require_support

## Summary

```json
{
  "conversation_id": "manual-sim-0",
  "turns": 6,
  "simulated_outbound_count": 3,
  "blocked_turns": 3,
  "outbound_outbox_writes": 0,
  "side_effects": {
    "delivery": false,
    "workflows": false,
    "actions": false,
    "field_writes": false
  }
}
```
