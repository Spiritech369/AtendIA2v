# Manual Live Simulator Run (no-send)

Run: 2026_06_10_0012_r2_conv10
Agent: moto-credit-agent (version v1)
Tenant: manual-review-tenant
Mode: no_send | outbox=0 | side_effects=0

## Transcript

- C> hola
- A> ¡Hola! Soy tu asesor de motos. ¿En qué puedo ayudarte hoy?
- C> quiero una moto
- A> ¡Genial! Para ayudarte a elegir la moto adecuada, primero necesito saber un par de cosas. ¿Cuánto tiempo llevas trabajando en tu empleo actual?
- C> tengo 22 años trabajando
- A> Perfecto, entonces llevas 22 años trabajando. ¿Cómo recibes tus ingresos? Puede ser por nómina, transferencia, efectivo o si trabajas por tu cuenta.
- C> me pagan por nómina
- A> Recibo tu mensaje, me dices que te pagan por nómina. Con 22 años de antigüedad laboral y recibiendo ingresos por nómina, puedes acceder a un plan de crédito estándar. El enganche es del 30%. ¿Te gustaría saber más sobre los modelos de motos disponibles?
- C> me interesa la metro
- A> Con 22 años de antigüedad laboral y recibiendo ingresos por nómina, puedes acceder a un plan de crédito estándar. Para la moto Metro, el precio es de $32,500 y el enganche es de $9,750, con un pago semanal de $689 durante 52 semanas. ¿Te gustaría avanzar con el proceso o saber más sobre otros modelos?
- C> qué ocupo
- A> Para la moto Metro, el precio es de $32,500 y el enganche es de $9,750, con un pago semanal de $689 durante 52 semanas. ¿Te gustaría avanzar con el proceso o saber más sobre otros modelos?
- C> prefiero que me atienda una persona
- A> Entiendo que prefieres hablar con una persona. Te puedo pasar con un asesor humano del equipo de ventas. ¿Te gustaría que lo haga ahora?
- C> me puedes pasar con alguien?
- A> Te puedo pasar con un asesor humano del equipo de ventas. ¿Te gustaría que lo haga ahora?

## Turns

- turn 1: send_decision=no_send, outbound=yes
- turn 2: send_decision=no_send, outbound=yes
- turn 3: send_decision=no_send, outbound=yes
- turn 4: send_decision=no_send, outbound=yes
- turn 5: send_decision=no_send, outbound=yes
- turn 6: send_decision=no_send, outbound=yes
- turn 7: send_decision=no_send, outbound=yes
- turn 8: send_decision=no_send, outbound=yes

## Summary

```json
{
  "conversation_id": "manual-sim-0",
  "turns": 8,
  "simulated_outbound_count": 8,
  "blocked_turns": 0,
  "outbound_outbox_writes": 0,
  "side_effects": {
    "delivery": false,
    "workflows": false,
    "actions": false,
    "field_writes": false
  }
}
```
