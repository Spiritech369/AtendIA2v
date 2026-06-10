# Manual Live Simulator Run (no-send)

Run: 2026_06_10_0119_r5o_conv04
Agent: moto-credit-agent (version v1)
Tenant: manual-review-tenant
Mode: no_send | outbox=0 | side_effects=0

## Transcript

- C> buenas
- A> ¡Hola! Soy tu asesor de motos a crédito por WhatsApp. ¿En qué puedo ayudarte hoy?
- C> quiero crédito para una moto
- A> ¡Perfecto! Para ayudarte con el crédito, necesito saber un poco más sobre ti. ¿Cuánto tiempo llevas en tu trabajo actual?
- C> tengo negocio
- A> Gracias por compartirlo. ¿Cuánto tiempo llevas con tu negocio? Esto me ayudará a encontrar el plan de crédito adecuado para ti.
- C> vendo comida desde mi casa
- C> tengo 3 años con el negocio
- C> qué papeles ocupo
- C> cuánto tendría que dar
- A> Para tu crédito, necesitarás estos papeles:
- Identificación oficial vigente
- Comprobante de domicilio reciente
- Comprobante de ingresos de los últimos 3 meses (pueden ser estados de cuenta si no tienes recibos de nómina)

Para saber cuánto tendrías que dar de enganche, ¿ya tienes en mente alguna moto específica o necesitas ayuda para elegir?

## Turns

- turn 1: send_decision=no_send, outbound=yes
- turn 2: send_decision=no_send, outbound=yes
- turn 3: send_decision=no_send, outbound=yes
- turn 4: send_decision=no_send, outbound=no, no_send_reason=claim_missing_source_ref,claim_missing_source_ref
- turn 5: send_decision=no_send, outbound=no, no_send_reason=claim_missing_source_ref,claim_missing_source_ref,claim_missing_source_ref
- turn 6: send_decision=no_send, outbound=no, no_send_reason=claim_missing_source_ref
- turn 7: send_decision=no_send, outbound=yes

## Failures

- turn 4: claim_missing_source_ref,claim_missing_source_ref
- turn 5: claim_missing_source_ref,claim_missing_source_ref,claim_missing_source_ref
- turn 6: claim_missing_source_ref

## Summary

```json
{
  "conversation_id": "manual-sim-0",
  "turns": 7,
  "simulated_outbound_count": 4,
  "blocked_turns": 3,
  "outbound_outbox_writes": 0,
  "side_effects": {
    "delivery": false,
    "workflows": false,
    "actions": false,
    "field_writes": false
  }
}
```
