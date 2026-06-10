# Manual Live Simulator Run (no-send)

Run: 2026_06_10_0007_r2_conv04
Agent: moto-credit-agent (version v1)
Tenant: manual-review-tenant
Mode: no_send | outbox=0 | side_effects=0

## Transcript

- C> buenas
- A> ¡Buenas! ¿En qué puedo ayudarte hoy con respecto a las motos o el crédito?
- C> quiero crédito para una moto
- A> ¡Claro! Para ayudarte con el crédito para una moto, primero necesito saber tu antigüedad laboral. ¿Cuánto tiempo llevas trabajando?
- C> tengo negocio
- A> Entiendo que tienes un negocio. Para avanzar con el crédito, necesito saber cuánto tiempo llevas trabajando en tu negocio. ¿Podrías decirme tu antigüedad laboral?
- C> vendo comida desde mi casa
- A> ¿Cuánto tiempo llevas trabajando en tu negocio? Esto me ayudará a avanzar con el crédito para la moto.
- C> tengo 3 años con el negocio
- A> Tienes 3 años con tu negocio, gracias por compartirlo. Ahora, ¿cómo recibes tus ingresos? ¿Es a través de ventas, transferencias, efectivo u otro método?
- C> qué papeles ocupo
- A> Para el crédito de la moto, necesitas los siguientes documentos:
- Identificación oficial vigente
- Comprobante de domicilio reciente
- Comprobante de ingresos de los últimos 3 meses (los estados de cuenta sirven si no tienes recibos de nómina).

Si necesitas más información o quieres avanzar con el proceso, ¡házmelo saber!
- C> cuánto tendría que dar
- A> Para el crédito de la moto, necesitas los siguientes documentos:
- Identificación oficial vigente
- Comprobante de domicilio reciente
- Comprobante de ingresos de los últimos 3 meses (los estados de cuenta sirven si no tienes recibos de nómina).

Si necesitas más información o quieres avanzar con el proceso, ¡házmelo saber!

## Turns

- turn 1: send_decision=no_send, outbound=yes
- turn 2: send_decision=no_send, outbound=yes
- turn 3: send_decision=no_send, outbound=yes
- turn 4: send_decision=no_send, outbound=yes
- turn 5: send_decision=no_send, outbound=yes
- turn 6: send_decision=no_send, outbound=yes
- turn 7: send_decision=no_send, outbound=yes

## Summary

```json
{
  "conversation_id": "manual-sim-0",
  "turns": 7,
  "simulated_outbound_count": 7,
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
