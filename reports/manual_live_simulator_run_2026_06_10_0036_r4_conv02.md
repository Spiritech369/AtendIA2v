# Manual Live Simulator Run (no-send)

Run: 2026_06_10_0036_r4_conv02
Agent: moto-credit-agent (version v1)
Tenant: manual-review-tenant
Mode: no_send | outbox=0 | side_effects=0

## Transcript

- C> hola
- A> ¡Hola! ¿En qué puedo ayudarte hoy con respecto a motos?
- C> quiero la opcion estandar trabajo por mi cuenta que necesito y cuanto cuesta
- A> Para el plan estándar trabajando por tu cuenta, necesitas presentar los siguientes documentos:

1. Identificación oficial vigente.
2. Comprobante de domicilio reciente.
3. Comprobante de ingresos de los últimos 3 meses (los estados de cuenta sirven si no tienes recibos de nómina).

Ahora, para poder darte el costo y enganche exactos, necesito saber qué modelo de moto te interesa. ¿Tienes alguno en mente?
- C> y si no tengo comprobantes?
- A> Si no tienes comprobantes de ingresos, te recomiendo hablar con un asesor humano que pueda ayudarte mejor con tu situación. Voy a conectarte con uno.
- C> está algo caro
- A> Entiendo que te preocupa el costo. Voy a conectarte con un asesor humano que podrá ayudarte mejor con tus dudas sobre precios y opciones.
- C> entonces qué me conviene
- A> Voy a conectarte con un asesor humano que podrá ayudarte a encontrar la mejor opción para ti.

## Turns

- turn 1: send_decision=no_send, outbound=yes
- turn 2: send_decision=no_send, outbound=yes
- turn 3: send_decision=no_send, outbound=yes
- turn 4: send_decision=no_send, outbound=yes
- turn 5: send_decision=no_send, outbound=yes

## Summary

```json
{
  "conversation_id": "manual-sim-0",
  "turns": 5,
  "simulated_outbound_count": 5,
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
