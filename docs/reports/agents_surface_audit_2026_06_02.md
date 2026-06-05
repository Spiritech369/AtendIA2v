# Agents Surface Audit - 2026-06-02

## Widget Classification

| Widget | Classification | Decision |
|---|---|---|
| Health score | NEEDS_REAL_DATA_REVIEW | keep if sourced from runtime/evals |
| Risk Radar | NEEDS_REAL_DATA_REVIEW | mark demo if seeded |
| Simulador de escenarios | USEFUL | use Eval/Simulation real |
| Knowledge Coverage | REAL_DATA_REQUIRED | use Knowledge OS v2 counts |
| Extraccion de campos | USEFUL | use Contact Memory v2 config/results |
| Onboarding readiness | REAL_DATA_REQUIRED | reflect knowledge, fields, lifecycle, test, publish, channel |
| Vista previa | USEFUL | use AgentRuntime v2 preview only |
| Workflows linked | USEFUL | now safer after workflow normalization |
| Publicar/pausar | USEFUL | keep disabled for no-send preview policy |
| Runtime v2 tab | REAL_DATA | keep |
| Agent Studio tab | REAL_DATA | keep |
| Knowledge tab | REAL_DATA_REQUIRED | show Knowledge OS v2 sources |
| Guardrails | USEFUL | keep |
| Extraction | USEFUL | keep |

## Dinamo Readiness

Readiness should show:

- Knowledge uploaded: true only from active Knowledge OS or legacy sources.
- Contact fields ready: true only official Dinamo fields present.
- Lifecycle ready: true when active tenant pipeline exists.
- Test passed: false until frontend review simulation passes.
- Published: false for live send; preview only.
- Channel connected: false; do not enable WhatsApp.

