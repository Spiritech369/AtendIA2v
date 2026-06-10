# Manual Live Simulator Run (no-send)

Run: 2026_06_10_0117_r5o_conv03
Agent: moto-credit-agent (version v1)
Tenant: manual-review-tenant
Mode: no_send | outbox=0 | side_effects=0

## Transcript

- C> hola
- A> ¡Hola! Soy tu asesor de motos a crédito. ¿En qué puedo ayudarte hoy?
- C> qué ocupo para sacar una moto
- C> pero dime los papeles primero
- C> tengo como 2 años trabajando
- C> me pagan por nómina
- C> quiero una económica
- A> Para sacar una moto a crédito, necesitas estos papeles:
- Identificación oficial vigente
- Comprobante de domicilio reciente
- Comprobante de ingresos de los últimos 3 meses (pueden ser estados de cuenta si no tienes recibos de nómina)

En cuanto a las motos económicas, tengo el modelo **Metro** que es una opción urbana y viene en colores rojo y azul. ¿Te gustaría más información sobre este modelo o ver otras opciones?

## Turns

- turn 1: send_decision=no_send, outbound=yes
- turn 2: send_decision=no_send, outbound=no, no_send_reason=hard_policy_unsupported:requirements_require_support
- turn 3: send_decision=no_send, outbound=no, no_send_reason=hard_policy_unsupported:requirements_require_support
- turn 4: send_decision=no_send, outbound=no, no_send_reason=hard_policy_unsupported:requirements_require_support
- turn 5: send_decision=no_send, outbound=no, no_send_reason=claim_missing_source_ref
- turn 6: send_decision=no_send, outbound=yes

## Failures

- turn 2: hard_policy_unsupported:requirements_require_support
- turn 3: hard_policy_unsupported:requirements_require_support
- turn 4: hard_policy_unsupported:requirements_require_support
- turn 5: claim_missing_source_ref

## Summary

```json
{
  "conversation_id": "manual-sim-0",
  "turns": 6,
  "simulated_outbound_count": 2,
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
