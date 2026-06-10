# Manual Live Simulator Run (no-send)

Run: 2026_06_10_0121_r5o_conv06
Agent: moto-credit-agent (version v1)
Tenant: manual-review-tenant
Mode: no_send | outbox=0 | side_effects=0

## Transcript

- C> hola
- A> ¡Hola! Soy tu asesor de motos a crédito. ¿En qué puedo ayudarte hoy?
- C> busco una moto barata
- A> Encontré una opción económica para ti: la moto **Metro**, que es de la categoría urbana y está disponible en colores rojo y azul. ¿Te gustaría saber más sobre esta moto o necesitas ayuda con algo más?
- C> tengo 18 meses trabajando
- A> Perfecto, ya tengo tu antigüedad laboral. La moto **Metro** es una opción económica que podría interesarte. Está en la categoría urbana y viene en colores rojo y azul. ¿Te gustaría saber más sobre el financiamiento o algún otro detalle?
- C> me pagan por transferencia
- C> me gusta la opción estándar
- C> cuánto me queda
- C> está muy caro
- C> hay una más barata?

## Turns

- turn 1: send_decision=no_send, outbound=yes
- turn 2: send_decision=no_send, outbound=yes
- turn 3: send_decision=no_send, outbound=yes
- turn 4: send_decision=no_send, outbound=no, no_send_reason=llm_turn_provider_failed
- turn 5: send_decision=no_send, outbound=no, no_send_reason=llm_turn_provider_failed
- turn 6: send_decision=no_send, outbound=no, no_send_reason=llm_turn_provider_failed
- turn 7: send_decision=no_send, outbound=no, no_send_reason=llm_turn_provider_failed
- turn 8: send_decision=no_send, outbound=no, no_send_reason=llm_turn_provider_failed

## Failures

- turn 4: llm_turn_provider_failed
- turn 5: llm_turn_provider_failed
- turn 6: llm_turn_provider_failed
- turn 7: llm_turn_provider_failed
- turn 8: llm_turn_provider_failed

## Summary

```json
{
  "conversation_id": "manual-sim-0",
  "turns": 8,
  "simulated_outbound_count": 3,
  "blocked_turns": 5,
  "outbound_outbox_writes": 0,
  "side_effects": {
    "delivery": false,
    "workflows": false,
    "actions": false,
    "field_writes": false
  }
}
```
