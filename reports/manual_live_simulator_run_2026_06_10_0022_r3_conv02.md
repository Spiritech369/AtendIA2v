# Manual Live Simulator Run (no-send)

Run: 2026_06_10_0022_r3_conv02
Agent: moto-credit-agent (version v1)
Tenant: manual-review-tenant
Mode: no_send | outbox=0 | side_effects=0

## Transcript

- C> hola
- A> ¡Hola! ¿En qué puedo ayudarte hoy con respecto a motos?
- C> quiero la opcion estandar trabajo por mi cuenta que necesito y cuanto cuesta
- C> y si no tengo comprobantes?
- A> Si no tienes comprobantes, lo mejor es hablar con un asesor humano que pueda ayudarte a encontrar la mejor opción. ¿Te gustaría que te pase con uno?
- C> está algo caro
- A> Entiendo que te preocupa el costo. Te puedo pasar con un asesor humano que te ayude a encontrar la mejor opción. ¿Te gustaría que lo haga?
- C> entonces qué me conviene
- A> Puedo pasarte con un asesor humano que te ayudará a encontrar la opción que más te convenga. ¿Te gustaría que lo haga?

## Turns

- turn 1: send_decision=no_send, outbound=yes
- turn 2: send_decision=no_send, outbound=no, no_send_reason=required_tool_skipped:missing_precondition:selected_model
- turn 3: send_decision=no_send, outbound=yes
- turn 4: send_decision=no_send, outbound=yes
- turn 5: send_decision=no_send, outbound=yes

## Failures

- turn 2: required_tool_skipped:missing_precondition:selected_model

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
