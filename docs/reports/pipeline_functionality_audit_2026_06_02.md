# Pipeline Functionality Audit - 2026-06-02

## Functional Map

| Function | Meaning | v2 Decision |
|---|---|---|
| stage list | lifecycle stages from tenant pipeline | active |
| kanban columns | lead grouping by current stage | active |
| stage counts | count contacts/conversations per stage | active |
| stale leads | operational health signal | active if real data |
| no activity 24h | follow-up risk signal | active if real data |
| unassigned | ownership queue signal | active |
| orphan leads | missing owner/stage data | useful, needs real counts |
| handoffs | human escalation surface | active |
| stuck docs | document checklist incomplete signal | active |
| appointments today | calendar/lifecycle context | useful if connected |
| score high | prioritization widget | needs REAL_DATA marking |
| stage editor | tenant lifecycle config | active |
| stage key | stable stage id | active |
| terminal stage | no automatic forward movement | active |
| manual vs automatic | prevents runtime from moving manual-only stages | active |
| allow backwards movement | editor/runtime transition policy | active if defined |
| timeout hours | stale/stuck rule input | active if defined |
| mode/composer binding | legacy `behavior_mode`/`mode_prompts` | keep as guidance only |
| suggested next action | operator assist | active if sourced from runtime |
| health panel | ops status | needs real-vs-demo labeling |
| realtime activity | stream updates | active if websocket connected |

## Composer Mode Decision

Current stage config uses `behavior_mode` / `mode_prompts`. For AgentRuntime v2 this must be treated as Stage Guidance: it can orient context and allowed actions, but must not write or override `TurnOutput.final_message`.

Recommended UI copy:

- Rename `Modo del Composer` to `Legacy composer mode` for legacy tenants.
- For v2 tenants show `Guia de etapa`.
- Add operator note: `Orienta al agente; no reemplaza AgentRuntime.`

## Dinamo Critical Rules

- `sistema` and `cliente_cerrado` must remain manual-only.
- `plan` auto-entry requires `Plan_Credito` + `Plan_Enganche`.
- `cliente_potencial` auto-entry requires `Plan_Credito` + `Plan_Enganche` + `Moto` + `Cotizacion_Enviada`.
- Pipeline editor must not write final customer copy.

