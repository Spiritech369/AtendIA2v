# Manual Live Simulator Run (no-send)

Run: 2026_06_10_0213_r7o_conv01
Agent: moto-credit-agent (version v1)
Tenant: manual-review-tenant
Mode: no_send | outbox=0 | side_effects=0

## Transcript

- C> hola
- A> ¡Hola! Soy tu asesor de motos a crédito. ¿En qué puedo ayudarte hoy?
- C> busco una moto a crédito
- A> ¡Perfecto! Para ayudarte mejor, ¿tienes algún modelo o color en mente, o prefieres que te sugiera opciones según tu presupuesto?
- C> tengo 15 meses trabajando
- A> Gracias por compartir tu antigüedad laboral. Ahora, ¿cómo recibes tus ingresos? Esto me ayudará a verificar el plan de crédito adecuado para ti.
- C> me pagan por transferencia
- A> Con 15 meses de antigüedad laboral y recibiendo tus ingresos por transferencia, calificas para el "plan semanal estándar". Este plan requiere un enganche del 30% y los pagos son semanales. 

Si tienes alguna moto en mente o necesitas más información, ¡avísame!
- C> no me dan nomina
- A> Con 15 meses de antigüedad laboral y recibiendo tus ingresos por transferencia, calificas para el "plan semanal estándar". Este plan requiere un enganche del 30% y los pagos son semanales. 

Si tienes alguna moto en mente o necesitas más información, ¡avísame!
- C> me interesa la DNM2.5
- A> La DNM2.5 es una moto de categoría trabajo y está disponible en colores negro y rojo. Pertenece a la gama media. Si quieres saber el precio exacto y el enganche, puedo verificarlo para ti. ¿Te gustaría que lo haga?
- C> qué ocupo para avanzar
- A> Para avanzar con el crédito de la DNM2.5, necesitas:

- Identificación oficial vigente
- Comprobante de domicilio reciente
- Comprobante de ingresos de los últimos 3 meses (pueden ser estados de cuenta si no tienes recibos de nómina)

Si tienes alguna otra pregunta o necesitas más detalles, ¡aquí estoy para ayudarte!
- C> cuánto doy de enganche?
- A> El enganche para la DNM2.5 es de $9,750 MXN. El precio total de la moto es de $32,500 MXN, y los pagos semanales son de $689 MXN durante 52 semanas. 

Si necesitas más información o quieres avanzar con el proceso, ¡dímelo!

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
