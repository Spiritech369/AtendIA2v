# Manual Live Simulator Run (no-send)

Run: 2026_06_10_0044_r4_conv10
Agent: moto-credit-agent (version v1)
Tenant: manual-review-tenant
Mode: no_send | outbox=0 | side_effects=0

## Transcript

- C> hola
- A> ¡Hola! ¿En qué puedo ayudarte hoy con respecto a motos a crédito?
- C> quiero una moto
- A> ¡Genial! Para ayudarte mejor, ¿puedes decirme cuánto tiempo llevas trabajando y cómo recibes tus ingresos? Esto me ayudará a encontrar el plan de crédito adecuado para ti.
- C> tengo 22 años trabajando
- A> Perfecto, llevas 22 años trabajando. Ahora, ¿me puedes decir cómo recibes tus ingresos? Puede ser por nómina, transferencia, efectivo o si tienes un negocio propio.
- C> me pagan por nómina
- A> Con 22 años de antigüedad laboral y recibiendo ingresos por nómina, puedes acceder al plan semanal estándar. Este plan requiere un enganche del 30%. Si en algún momento decides tener un negocio propio y estás dado de alta en el SAT, podrías acceder a un enganche del 20%. 

¿Tienes algún modelo de moto en mente o te gustaría que te muestre algunas opciones?
- C> me interesa la metro
- A> ¡Excelente elección! La moto Metro está disponible en colores rojo y azul. Es una opción económica y perfecta para la ciudad. 

Si quieres, puedo verificar el precio y el enganche exactos para ti. ¿Te gustaría que lo haga?
- C> qué ocupo
- A> Para adquirir la moto Metro, necesitas presentar los siguientes documentos:

1. Identificación oficial vigente.
2. Comprobante de domicilio reciente.
3. Comprobante de ingresos de los últimos 3 meses (los estados de cuenta sirven si no tienes recibos de nómina).

Si tienes todo listo, podemos avanzar con el proceso de crédito. ¿Te gustaría continuar?
- C> prefiero que me atienda una persona
- C> me puedes pasar con alguien?
- A> Claro, te conectaré con un asesor humano que podrá ayudarte mejor. Un momento, por favor.

## Turns

- turn 1: send_decision=no_send, outbound=yes
- turn 2: send_decision=no_send, outbound=yes
- turn 3: send_decision=no_send, outbound=yes
- turn 4: send_decision=no_send, outbound=yes
- turn 5: send_decision=no_send, outbound=yes
- turn 6: send_decision=no_send, outbound=yes
- turn 7: send_decision=no_send, outbound=no, no_send_reason=handoff_target_not_allowed
- turn 8: send_decision=no_send, outbound=yes

## Failures

- turn 7: handoff_target_not_allowed

## Summary

```json
{
  "conversation_id": "manual-sim-0",
  "turns": 8,
  "simulated_outbound_count": 7,
  "blocked_turns": 1,
  "outbound_outbox_writes": 0,
  "side_effects": {
    "delivery": false,
    "workflows": false,
    "actions": false,
    "field_writes": false
  }
}
```
