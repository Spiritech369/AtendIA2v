# Manual Live Simulator Run (no-send)

Run: 2026_06_10_0223_r7o_conv10
Agent: moto-credit-agent (version v1)
Tenant: manual-review-tenant
Mode: no_send | outbox=0 | side_effects=0

## Transcript

- C> hola
- A> ¡Hola! Soy tu asesor de motos a crédito. ¿En qué puedo ayudarte hoy?
- C> quiero una moto
- A> ¡Genial! ¿Tienes algún modelo o color en mente, o prefieres que te sugiera algunas opciones?
- C> tengo 22 años trabajando
- A> Perfecto, con 22 años de antigüedad laboral tienes muchas opciones para el crédito. ¿Cómo recibes tus ingresos: nómina, transferencia, efectivo o tienes negocio propio?
- C> me pagan por nómina
- A> Perfecto, con tus 22 años de antigüedad laboral y pago por nómina, calificas para el **plan semanal estándar**. Este plan tiene un enganche del 30% y pagos semanales. 

¿Te gustaría que busque opciones de motos para ti o tienes algún modelo en mente?
- C> me interesa la metro
- A> La moto **Metro** es una excelente opción urbana y está disponible en colores rojo y azul. Es de la categoría económica, ideal para moverte por la ciudad.

¿Te gustaría que te confirme el precio y el enganche exactos para esta moto?
- C> qué ocupo
- A> Para el crédito de la moto Metro, necesitas:
- Identificación oficial vigente
- Comprobante de domicilio reciente
- Comprobante de ingresos de los últimos 3 meses (pueden ser estados de cuenta si no tienes recibos de nómina)

¿Te gustaría que te confirme el precio y el enganche exactos para esta moto?
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
