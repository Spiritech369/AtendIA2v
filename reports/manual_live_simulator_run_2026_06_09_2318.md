# Manual Live Simulator Run (no-send)

Run: 2026_06_09_2318
Agent: generic-sales-agent (version v1)
Tenant: generic-sales-tenant
Mode: no_send | outbox=0 | side_effects=0

## Transcript

- C> hola
- A> ¡Hola! ¿En qué puedo ayudarte hoy?
- C> me interesa la opcion estandar, que necesito?
- A> Para la opción estándar, necesitas: 
- identificación válida 
- comprobante de domicilio 
- comprobante de ingresos reciente, si aplica.
- C> cuanto cuesta?
- A> La opción estándar cuesta $120 al mes.

## Turns

- turn 1: send_decision=no_send, outbound=yes
- turn 2: send_decision=no_send, outbound=yes
- turn 3: send_decision=no_send, outbound=yes

## Summary

```json
{
  "conversation_id": "manual-sim-0",
  "turns": 3,
  "simulated_outbound_count": 3,
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
