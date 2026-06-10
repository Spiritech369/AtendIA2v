# Manual Live Simulator Run (no-send)

Run: 2026_06_10_0214_r7o_conv02
Agent: moto-credit-agent (version v1)
Tenant: manual-review-tenant
Mode: no_send | outbox=0 | side_effects=0

## Transcript

- C> hola
- A> ¡Hola! Soy tu asesor de motos a crédito. ¿En qué puedo ayudarte hoy?
- C> quiero la opcion estandar trabajo por mi cuenta que necesito y cuanto cuesta
- C> y si no tengo comprobantes?
- A> Para trabajar por tu cuenta, no es obligatorio tener comprobantes formales, pero sí ayuda tener alguna forma de demostrar tus ingresos, como estados de cuenta o facturas. La lista exacta de documentos se confirma con el sistema según tu tipo de ingreso. Si quieres, puedo verificar los requisitos exactos para ti. 

Para avanzar, ¿me puedes decir cuánto tiempo llevas trabajando por tu cuenta?
- C> está algo caro
- A> Para el crédito de moto trabajando por tu cuenta, necesitas:
- Identificación oficial vigente
- Comprobante de domicilio reciente
- Comprobante de ingresos de los últimos 3 meses (pueden ser estados de cuenta si no tienes recibos de nómina)

Sobre el costo, puedo verificar el precio exacto de una moto específica si me dices cuál te interesa. ¿Tienes algún modelo en mente?
- C> entonces qué me conviene
- A> Para encontrar el plan de crédito que más te conviene, necesito saber cuánto tiempo llevas trabajando por tu cuenta. Esto me ayudará a verificar las opciones disponibles para ti. ¿Me puedes decir tu antigüedad laboral?

## Turns

- turn 1: send_decision=no_send, outbound=yes
- turn 2: send_decision=no_send, outbound=no, no_send_reason=internal_text_visible
- turn 3: send_decision=no_send, outbound=yes
- turn 4: send_decision=no_send, outbound=yes
- turn 5: send_decision=no_send, outbound=yes

## Failures

- turn 2: internal_text_visible

## Summary

```json
{
  "conversation_id": "manual-sim-0",
  "turns": 5,
  "simulated_outbound_count": 4,
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
