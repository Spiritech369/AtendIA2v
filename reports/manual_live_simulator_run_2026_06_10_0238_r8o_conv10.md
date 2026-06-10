# Manual Live Simulator Run (no-send)

Run: 2026_06_10_0238_r8o_conv10
Agent: moto-credit-agent (version v1)
Tenant: manual-review-tenant
Mode: no_send | outbox=0 | side_effects=0

## Transcript

- C> hola
- A> ¡Hola! Soy tu asesor de motos a crédito. ¿En qué puedo ayudarte hoy?
- C> quiero una moto
- A> ¡Perfecto! ¿Tienes algún modelo o color en mente, o prefieres que te muestre algunas opciones?
- C> tengo 22 años trabajando
- A> Gracias por compartir tu antigüedad laboral. Ahora, ¿cómo recibes tus ingresos? Esto me ayudará a encontrar el plan de crédito adecuado para ti.
- C> me pagan por nómina
- A> Con 22 años de antigüedad laboral y recibiendo ingresos por nómina, calificas para nuestro **plan semanal estándar**. Este plan requiere un enganche del 30% y los pagos son semanales. 

¿Te gustaría que te muestre algunas opciones de motos o tienes algún modelo en mente?
- C> me interesa la metro
- A> La moto **Metro** es una excelente opción en la categoría urbana. Está disponible en colores rojo y azul, y pertenece a la gama económica. 

¿Te gustaría que te ayude a conocer el precio y el enganche exactos para este modelo?
- C> qué ocupo
- A> Para el crédito de la moto Metro, necesitas:

- Identificación oficial vigente
- Comprobante de domicilio reciente
- Comprobante de ingresos de los últimos 3 meses (pueden ser estados de cuenta si no tienes recibos de nómina)

Si tienes alguna otra pregunta o necesitas más ayuda, aquí estoy para asistirte.
- C> prefiero que me atienda una persona
- A> Te conecto con un asesor humano de ventas para que te ayude personalmente.
- C> me puedes pasar con alguien?
- A> Te conecto con un asesor humano de ventas para que te ayude personalmente.

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
