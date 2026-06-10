# Manual Live Simulator Run (no-send)

Run: 2026_06_09_2352_conv02_caotico
Agent: moto-credit-agent (version v1)
Tenant: manual-review-tenant
Mode: no_send | outbox=0 | side_effects=0

## Transcript

- C> hola
- A> ¡Hola! ¿En qué puedo ayudarte hoy con respecto a las motos?
- C> quiero la opcion estandar trabajo por mi cuenta que necesito y cuanto cuesta
- C> y si no tengo comprobantes?
- A> Para el plan estándar de crédito, necesitarás los siguientes documentos:
- Identificación oficial vigente
- Comprobante de domicilio reciente
- Comprobante de ingresos de los últimos 3 meses (los estados de cuenta sirven si no tienes recibos de nómina).

Si no tienes comprobantes de ingresos, podemos revisar otras opciones. ¿Te gustaría que te ayude con eso?
- C> está algo caro
- A> Entiendo que puede parecer caro. Para poder ayudarte mejor, ¿puedes decirme cuál es tu antigüedad laboral?
- C> entonces qué me conviene
- A> Para poder ayudarte mejor, necesito saber tu antigüedad laboral. ¿Cuánto tiempo llevas trabajando por tu cuenta?

## Turns

- turn 1: send_decision=no_send, outbound=yes
- turn 2: send_decision=no_send, outbound=no, no_send_reason=required_tool_skipped:missing_precondition:employment_seniority
- turn 3: send_decision=no_send, outbound=yes
- turn 4: send_decision=no_send, outbound=yes
- turn 5: send_decision=no_send, outbound=yes

## Failures

- turn 2: required_tool_skipped:missing_precondition:employment_seniority

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
