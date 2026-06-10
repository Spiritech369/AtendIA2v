# Manual Live Simulator Run (no-send)

Run: 2026_06_10_0006_r2_conv02
Agent: moto-credit-agent (version v1)
Tenant: manual-review-tenant
Mode: no_send | outbox=0 | side_effects=0

## Transcript

- C> hola
- A> ¡Hola! Soy tu asesor de motos. ¿En qué puedo ayudarte hoy?
- C> quiero la opcion estandar trabajo por mi cuenta que necesito y cuanto cuesta
- A> Para la opción estándar de crédito, necesito saber tu antigüedad laboral. ¿Cuánto tiempo llevas trabajando en tu actividad actual?
- C> y si no tengo comprobantes?
- A> Si no tienes comprobantes, aún puedes calificar para el crédito, pero necesitaré saber tu antigüedad laboral y cómo recibes tus ingresos. ¿Cuánto tiempo llevas trabajando en tu actividad actual?
- C> está algo caro
- A> Entiendo que te parece caro. Para poder ofrecerte una opción más adecuada, necesito saber tu antigüedad laboral. ¿Cuánto tiempo llevas trabajando en tu actividad actual?
- C> entonces qué me conviene
- A> Para poder ofrecerte la mejor opción de crédito, necesito saber tu antigüedad laboral. ¿Cuánto tiempo llevas trabajando en tu actividad actual?

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
