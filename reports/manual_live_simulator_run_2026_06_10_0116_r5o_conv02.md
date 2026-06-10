# Manual Live Simulator Run (no-send)

Run: 2026_06_10_0116_r5o_conv02
Agent: moto-credit-agent (version v1)
Tenant: manual-review-tenant
Mode: no_send | outbox=0 | side_effects=0

## Transcript

- C> hola
- A> ¡Hola! Soy tu asesor de motos a crédito. ¿En qué puedo ayudarte hoy?
- C> quiero la opcion estandar trabajo por mi cuenta que necesito y cuanto cuesta
- C> y si no tengo comprobantes?
- C> está algo caro
- A> Entiendo, a veces el presupuesto es una preocupación. Para poder ayudarte mejor con el plan de crédito, ¿me puedes decir cuánto tiempo llevas trabajando por tu cuenta? Esto nos ayudará a encontrar la mejor opción para ti.
- C> entonces qué me conviene
- A> Para encontrar el mejor plan de crédito para ti, necesito saber cuánto tiempo llevas trabajando por tu cuenta. Esto nos ayudará a ajustar las opciones a tus necesidades. ¿Me puedes decir tu antigüedad laboral?

## Turns

- turn 1: send_decision=no_send, outbound=yes
- turn 2: send_decision=no_send, outbound=no, no_send_reason=claim_missing_source_ref
- turn 3: send_decision=no_send, outbound=no, no_send_reason=claim_missing_source_ref
- turn 4: send_decision=no_send, outbound=yes
- turn 5: send_decision=no_send, outbound=yes

## Failures

- turn 2: claim_missing_source_ref
- turn 3: claim_missing_source_ref

## Summary

```json
{
  "conversation_id": "manual-sim-0",
  "turns": 5,
  "simulated_outbound_count": 3,
  "blocked_turns": 2,
  "outbound_outbox_writes": 0,
  "side_effects": {
    "delivery": false,
    "workflows": false,
    "actions": false,
    "field_writes": false
  }
}
```
