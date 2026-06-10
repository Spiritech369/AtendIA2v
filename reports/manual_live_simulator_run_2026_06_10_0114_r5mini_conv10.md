# Manual Live Simulator Run (no-send)

Run: 2026_06_10_0114_r5mini_conv10
Agent: moto-credit-agent (version v1)
Tenant: manual-review-tenant
Mode: no_send | outbox=0 | side_effects=0

## Transcript

- C> hola
- A> ¡Hola! ¿En qué puedo ayudarte hoy con respecto a motos a crédito?
- C> quiero una moto
- A> ¡Genial! Para ayudarte mejor, necesito saber un poco más sobre ti. ¿Cuánto tiempo llevas trabajando en tu empleo actual?
- C> tengo 22 años trabajando
- A> Perfecto, con 22 años de antigüedad laboral, solo me falta saber cómo recibes tus ingresos: ¿por nómina, transferencia, efectivo o tienes un negocio propio?
- C> me pagan por nómina
- A> Con 22 años de antigüedad laboral y recibiendo ingresos por nómina, puedes acceder a un plan semanal estándar. El enganche es del 30%. 

Para iniciar, necesitarás presentar los siguientes documentos:
1. Identificación oficial vigente.
2. Comprobante de domicilio reciente.
3. Comprobante de ingresos de los últimos 3 meses (los estados de cuenta sirven si no tienes recibos de nómina).

¿Tienes algún modelo de moto en mente o necesitas opciones?
- C> me interesa la metro
- A> La moto Metro es una opción económica y está disponible en rojo y azul. Si te interesa, puedo ayudarte a verificar el precio y el enganche exactos. ¿Te gustaría proceder con eso?
- C> qué ocupo
- A> Para adquirir la moto Metro, necesitarás presentar los siguientes documentos:
1. Identificación oficial vigente.
2. Comprobante de domicilio reciente.
3. Comprobante de ingresos de los últimos 3 meses (los estados de cuenta sirven si no tienes recibos de nómina).

Si tienes todo listo, podemos avanzar con el proceso. ¿Te gustaría saber más sobre el precio y el enganche de la moto?
- C> prefiero que me atienda una persona
- A> Voy a conectar contigo a un asesor humano que te atenderá mejor. Un momento, por favor.
- C> me puedes pasar con alguien?
- A> Voy a conectar contigo a un asesor humano que te atenderá mejor. Un momento, por favor.

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
