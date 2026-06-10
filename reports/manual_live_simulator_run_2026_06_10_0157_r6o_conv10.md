# Manual Live Simulator Run (no-send)

Run: 2026_06_10_0157_r6o_conv10
Agent: moto-credit-agent (version v1)
Tenant: manual-review-tenant
Mode: no_send | outbox=0 | side_effects=0

## Transcript

- C> hola
- A> ¡Hola! Soy tu asesor digital para motos a crédito. ¿En qué puedo ayudarte hoy?
- C> quiero una moto
- A> ¡Genial! ¿Tienes algún modelo o color en mente, o prefieres que te muestre algunas opciones?
- C> tengo 22 años trabajando
- A> Perfecto, con 22 años de experiencia laboral tienes muchas opciones. ¿Cómo recibes tus ingresos: por nómina, transferencia, en efectivo o tienes un negocio propio? Esto me ayudará a encontrar el mejor plan de crédito para ti.
- C> me pagan por nómina
- A> Con 22 años de experiencia y recibiendo tus ingresos por nómina, calificas para el **plan semanal estándar**. Este plan tiene un enganche del 30% y pagos semanales. Si tienes alguna moto en mente o necesitas más información, ¡dime y te ayudo!
- C> me interesa la metro
- A> La moto **Metro** es una excelente opción urbana y está disponible en colores rojo y azul. ¿Te gustaría saber el precio y el enganche exactos para esta moto?
- C> qué ocupo
- A> Para el plan de crédito con la moto Metro, necesitas:

- Identificación oficial vigente
- Comprobante de domicilio reciente
- Comprobante de ingresos de los últimos 3 meses (pueden ser estados de cuenta si no tienes recibos de nómina)

Si tienes alguna otra pregunta o necesitas más detalles, aquí estoy para ayudarte.
- C> prefiero que me atienda una persona
- A> Claro, te conecto con un asesor humano de ventas ahora mismo.
- C> me puedes pasar con alguien?
- A> Claro, te conecto con un asesor humano de ventas ahora mismo.

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
