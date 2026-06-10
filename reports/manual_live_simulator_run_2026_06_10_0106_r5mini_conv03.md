# Manual Live Simulator Run (no-send)

Run: 2026_06_10_0106_r5mini_conv03
Agent: moto-credit-agent (version v1)
Tenant: manual-review-tenant
Mode: no_send | outbox=0 | side_effects=0

## Transcript

- C> hola
- A> ¡Hola! ¿En qué puedo ayudarte hoy con respecto a las motos?
- C> qué ocupo para sacar una moto
- A> Para poder decirte exactamente qué documentos necesitas, necesito saber cómo recibes tus ingresos. ¿Es por nómina, transferencia, efectivo o tienes un negocio propio?
- C> pero dime los papeles primero
- C> tengo como 2 años trabajando
- A> Perfecto, ya tengo tu antigüedad laboral de 2 años. Ahora, ¿cómo recibes tus ingresos? ¿Es por nómina, transferencia, efectivo o tienes un negocio propio?
- C> me pagan por nómina
- C> quiero una económica
- A> Para sacar una moto con financiamiento, necesitas los siguientes documentos:

1. Identificación oficial vigente.
2. Comprobante de domicilio reciente.
3. Comprobante de ingresos de los últimos 3 meses (pueden ser estados de cuenta si no tienes recibos de nómina).

Ahora, ¿tienes en mente algún modelo específico o color que te gustaría? Así puedo ayudarte a encontrar opciones económicas.

## Turns

- turn 1: send_decision=no_send, outbound=yes
- turn 2: send_decision=no_send, outbound=yes
- turn 3: send_decision=no_send, outbound=no, no_send_reason=hard_policy_unsupported:requirements_require_support
- turn 4: send_decision=no_send, outbound=yes
- turn 5: send_decision=no_send, outbound=no, no_send_reason=llm_turn_provider_failed
- turn 6: send_decision=no_send, outbound=yes

## Failures

- turn 3: hard_policy_unsupported:requirements_require_support
- turn 5: llm_turn_provider_failed

## Summary

```json
{
  "conversation_id": "manual-sim-0",
  "turns": 6,
  "simulated_outbound_count": 4,
  "blocked_turns": 2,
  "outbound_outbox_writes": 0,
  "side_effects": {
    "delivery": false,
    "workflows": false,
    "actions": false,
    "field_writes": false
  }
}
```
