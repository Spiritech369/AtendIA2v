# Context-aware in-window follow-ups (design)

Fecha: 2026-05-16
Estado: aprobado por el usuario (brainstorming), pendiente plan de implementación.

## Objetivo

Dentro de las primeras 24h, el follow-up lo genera **el mismo agente IA con
el contexto de la conversación** (como respond.io), no un string
hardcodeado. Tiempos configurables por tenant. Templates Meta >24h: fuera
de alcance (fase posterior).

## Estado actual (verificado en código)

- `runner/followup_scheduler.py`: agenda 3h+12h fijos tras cada outbound;
  `render_followup_body` devuelve **texto hardcodeado** (3h string fijo,
  12h plantilla con 2 variables). No usa composer/LLM ni historial.
- `queue/followup_worker.py`: cron sólido (quiet hours, rate-cap 50/tick,
  idempotente, cancel-on-inbound, reanclaje del reloj de silencio). Llama
  a `render_followup_body`.

## Decisiones (forks resueltos con el usuario)

1. **Guía propia de follow-up** por tenant (1 caja), no reusar RETENTION
   ni elegir modo por etapa.
2. **Tiempos configurables por tenant** (no 3h/12h fijos).
3. **Enfoque A**: el worker arma el contexto y llama al **composer**
   directamente. (B inbound sintético y C plantilla sin LLM descartados.)

## Diseño

### Config (PipelineDefinition, mismo patrón que `mode_prompts`)

```
followup: {
  guidance: str = ""                 # "Guía de follow-up" del operador
  schedule_hours: list[int] = [3,12] # 1–23h, 1–5 entradas, únicas
}
```

No-regresión: `guidance` vacía **o** sin OpenAI key → fallback a
`render_followup_body` (texto actual). Tenant existente sin `followup` →
default `[3,12]` + vacío → idéntico a hoy hasta que el operador escriba la
guía. (Análogo a la migración 053 de `mode_prompts`.)

### Flujo

- **Agendado**: `schedule_followups_after_outbound` lee
  `pipeline.followup.schedule_hours` e inserta una fila pendiente por hora
  (`kind=silence_{h}h`, `run_at=now()+h`), idempotente por
  (conversation, kind) como hoy.
- **Disparo**: `poll_followups`, al vencer una fila, arma el contexto
  (historial últimos N turnos, `extracted_data` vivo, `current_stage`,
  `agent.system_prompt` + guardrails, `brand_facts`, `tone`) y llama a
  `build_composer_prompt`/composer con `mode_guidance =
  pipeline.followup.guidance` + una línea de meta ("cliente lleva {h}h en
  silencio, recordatorio #{n}"). Enquía el texto generado como outbound;
  marca `sent`. Quiet hours / rate-cap / idempotencia / cancel-on-inbound
  / reanclaje: sin cambios.
- **Sin nuevo FlowMode**: se reutiliza el composer pasando
  `mode_guidance` (gana sobre el default); `flow_mode=SUPPORT` como
  portador. Decisión deliberada para no tocar el contrato de 6 modos ni
  los snapshots.

### Errores / seguridad

Composer ya aplica guardrails + anti-alucinación (sin `action_payload`
no inventa precios). LLM falla o sin key → fallback a
`render_followup_body` (no se borra). El cron nunca truena ni se salta
filas.

### Frontend

PipelineEditor: sección colapsable "Follow-up (dentro de 24h)" = un
`Textarea` para `guidance` + lista editable de horas (add/quitar,
validada 1–23, máx 5). Round-trip por el parse/serialise existente;
extender la preservación de `put_pipeline` (la de `mode_prompts`) para
blindar también `followup`.

### Pruebas (TDD)

- Contrato: validación de `FollowupConfig` (rango/longitud/únicas, default).
- Scheduler: 1 fila por hora configurada; idempotente.
- Worker: guía+key → composer recibe la guía + historial/extracted/
  guardrails (recording composer); vacío **o** sin key → fallback estático
  (no-regresión).
- `put_pipeline` preserva `followup` cuando el body lo omite.
- Frontend: parse/serialise round-trip de `followup`; typecheck; unit.

## Fuera de alcance

Templates Meta >24h; disparadores especiales (OBSTACLE 2h/24h) — las horas
configurables + la guía con contexto lo cubren de forma genérica.
