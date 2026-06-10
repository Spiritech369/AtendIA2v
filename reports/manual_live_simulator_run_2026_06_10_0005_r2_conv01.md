# Manual Live Simulator Run (no-send)

Run: 2026_06_10_0005_r2_conv01
Agent: moto-credit-agent (version v1)
Tenant: manual-review-tenant
Mode: no_send | outbox=0 | side_effects=0

## Transcript

- C> hola
- A> ¡Hola! Soy tu asesor de motos. ¿En qué puedo ayudarte hoy?
- C> busco una moto a crédito
- A> ¡Genial! Para ayudarte a encontrar la moto a crédito, primero necesito saber un par de cosas. ¿Cuál es tu antigüedad laboral?
- C> tengo 15 meses trabajando
- A> Perfecto, tienes 15 meses trabajando. ¿Cómo recibes tus ingresos? (por ejemplo, nómina, transferencia, efectivo o negocio propio) Esto me ayudará a encontrar el mejor plan de crédito para ti.
- C> me pagan por transferencia
- A> Recibo que te pagan por transferencia. Con 15 meses de antigüedad laboral y tus ingresos por transferencia, puedes acceder a un plan de crédito estándar. El enganche sería del 30%. ¿Te gustaría saber más sobre los modelos de motos disponibles?
- C> no me dan nomina
- A> Con 15 meses de antigüedad laboral y tus ingresos por transferencia, puedes acceder a un plan de crédito estándar. El enganche sería del 30%. ¿Te gustaría saber más sobre los modelos de motos disponibles?
- C> me interesa la DNM2.5
- A> Con 15 meses de antigüedad laboral y tus ingresos por transferencia, puedes acceder a un plan de crédito estándar. El enganche sería de 9,750 MXN y el precio de la DNM2.5 es de 32,500 MXN. ¿Te gustaría continuar con el proceso o necesitas más información sobre otro modelo?
- C> qué ocupo para avanzar
- A> Para avanzar con la compra de la DNM2.5, necesitas un enganche de 9,750 MXN y el precio total es de 32,500 MXN. ¿Te gustaría continuar con el proceso o necesitas más información sobre otro modelo?
- C> cuánto doy de enganche?
- A> Para avanzar con la compra de la DNM2.5, necesitas presentar los siguientes documentos:
1. Identificación oficial vigente.
2. Comprobante de domicilio reciente.
3. Comprobante de ingresos de los últimos 3 meses (estados de cuenta sirven si no hay recibos de nómina).

¿Te gustaría continuar con el proceso o necesitas más información sobre otro modelo?

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
