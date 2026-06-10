# Manual Live Simulator Run (no-send)

Run: 2026_06_10_0036_r4_conv01
Agent: moto-credit-agent (version v1)
Tenant: manual-review-tenant
Mode: no_send | outbox=0 | side_effects=0

## Transcript

- C> hola
- A> ¡Hola! ¿En qué puedo ayudarte hoy con respecto a motos?
- C> busco una moto a crédito
- A> ¡Perfecto! Para ayudarte mejor, necesito saber un par de cosas. ¿Cuánto tiempo llevas trabajando (antigüedad laboral) y cómo recibes tus ingresos (nómina, transferencia, efectivo o negocio propio)? Esto me ayudará a encontrar el plan de crédito adecuado para ti.
- C> tengo 15 meses trabajando
- A> Gracias por la información. Ahora, ¿cómo recibes tus ingresos? Puede ser por nómina, transferencia, efectivo o si tienes un negocio propio.
- C> me pagan por transferencia
- A> Con 15 meses de antigüedad laboral y recibiendo tus ingresos por transferencia, puedes acceder al **plan semanal estándar**. Este plan requiere un enganche del **30%**. Si tuvieras un negocio propio y estuvieras dado de alta en el SAT, podrías acceder a un enganche del **20%**. 

¿Te gustaría ver opciones de motos disponibles? ¿Tienes algún modelo en mente?
- C> no me dan nomina
- A> Entiendo, si no recibes nómina y prefieres hablar con un asesor humano para que te ayude mejor, puedo conectarte con uno. ¿Te gustaría que lo haga?
- C> me interesa la DNM2.5
- A> ¡Genial! La DNM2.5 está disponible en colores negro y rojo. Si deseas, puedo verificar el precio y el enganche exactos para ti. ¿Te gustaría que lo haga?
- C> qué ocupo para avanzar
- A> Para avanzar con tu crédito para la DNM2.5, necesitas presentar los siguientes documentos:

1. Identificación oficial vigente.
2. Comprobante de domicilio reciente.
3. Comprobante de ingresos de los últimos 3 meses (puedes usar estados de cuenta si no tienes recibos de nómina).

¿Te gustaría que te ayude con algo más o prefieres hablar con un asesor humano?
- C> cuánto doy de enganche?
- A> Para la DNM2.5, el enganche es de **9,750 MXN**. El precio total de la moto es de **32,500 MXN**. Si necesitas más información o ayuda, ¡dímelo!

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
