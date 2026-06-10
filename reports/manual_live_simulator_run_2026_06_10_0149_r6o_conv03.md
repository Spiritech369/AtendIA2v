# Manual Live Simulator Run (no-send)

Run: 2026_06_10_0149_r6o_conv03
Agent: moto-credit-agent (version v1)
Tenant: manual-review-tenant
Mode: no_send | outbox=0 | side_effects=0

## Transcript

- C> hola
- A> ¡Hola! Soy tu asesor digital para motos a crédito. ¿En qué puedo ayudarte hoy?
- C> qué ocupo para sacar una moto
- A> Para saber exactamente qué necesitas para sacar una moto a crédito, necesito saber cómo recibes tus ingresos: ¿por nómina, transferencia, efectivo o tienes un negocio propio? Esto me ayudará a darte la información precisa sobre los requisitos. 😊
- C> pero dime los papeles primero
- C> tengo como 2 años trabajando
- C> me pagan por nómina
- C> quiero una económica
- A> Para sacar una moto a crédito, necesitas estos papeles:
- Identificación oficial vigente
- Comprobante de domicilio reciente
- Comprobante de ingresos de los últimos 3 meses (pueden ser estados de cuenta si no tienes recibos de nómina)

En cuanto a una moto económica, te recomiendo el modelo **Metro**. Es una moto urbana disponible en colores rojo y azul. ¿Te gustaría más información sobre este modelo o avanzar con el crédito?

## Turns

- turn 1: send_decision=no_send, outbound=yes
- turn 2: send_decision=no_send, outbound=yes
- turn 3: send_decision=no_send, outbound=no, no_send_reason=hard_policy_unsupported:requirements_require_support
- turn 4: send_decision=no_send, outbound=no, no_send_reason=hard_policy_unsupported:requirements_require_support
- turn 5: send_decision=no_send, outbound=no, no_send_reason=internal_text_visible
- turn 6: send_decision=no_send, outbound=yes

## Failures

- turn 3: hard_policy_unsupported:requirements_require_support
- turn 4: hard_policy_unsupported:requirements_require_support
- turn 5: internal_text_visible

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
