# `_archive/` — docs históricos

Todo lo que vive en este folder está **explícitamente reemplazado** por
[`docs/ESTADO-Y-GAPS.md`](../ESTADO-Y-GAPS.md). Se conserva por valor
histórico (timeline de decisiones, scope original de cada feature)
pero no debe consultarse como source-of-truth.

| Archivo / carpeta | Tipo | Reemplazado por |
|---|---|---|
| `AUDIT-2026-05-13.md` | Auditoría completa de 14 ítems del sidebar (2026-05-13) | §2-§6 + §0bis de `ESTADO-Y-GAPS.md` |
| `PROJECT_MAP.md` | Mapa antiguo del proyecto con scores por feature | §1 (mapa vs respond.io) + §9 (decision matrix) de `ESTADO-Y-GAPS.md` |
| `plans/2026-05-08-v1-parity-modular-plan.md` | Roadmap original V1→V2 | §0bis (Sprint A/B/C entregado) |
| `plans/2026-05-10-knowledge-base-module-{design,implementation}.md` | Plan del KB module (B2 scope) | §6 |
| `plans/2026-05-11-mock-demo-isolation-{design,implementation}.md` | Separar datos demo de tenants reales | §0bis A.2 (DBAdvisorProvider) + §6 (KB simulate B.3) |
| `plans/2026-05-12-placeholder-elimination-{design,implementation}.md` | Eliminar mocks de command centers | §0bis A.4 + B.3 |
| `plans/2026-05-12-rbac-and-observability-{design,implementation}.md` | RBAC por pantalla + UX de observabilidad | §1 §10, §4 (Operations Center) |
| `plans/2026-05-13-ai-field-extraction-{design,implementation}.md` | AI Field Extraction → customer.attrs | §2 (cableado, 22 tests verdes) |
| `plans/2026-05-13-baileys-integration-design.md` | Baileys QR como canal alterno | §2 (WhatsApp dual) + §0bis A.3 |
| `plans/2026-05-13-editable-contact-panel-{design,implementation}.md` | ContactPanel editable inline | §2 (ContactPanel rico) |
| `plans/2026-05-13-pipeline-automation-editor.md` | Editor de auto-enter rules | §3 (Rule builder) |
| `plans/2026-05-13-sidebar-redesign-{design,implementation}.md` | Sidebar reagrupado con badges | §1 (Workspace Settings parcial) |
| `plans/2026-05-13-tenant-onboarding.md` | Signup flow para tenants nuevos | §9 D1 (Forgot password — onboarding completo está post-PMF) |
| `plans/2026-05-13-workflow-builder-respondio.md` | Workflow builder estilo respond.io | §5 |
| `plans/2026-05-14-respond-io-style-maturity-audit.md` | Auditoría madurez vs respond.io | §1 + §8 (diferenciadores) |

## ¿Cuándo recurrir a este folder?

Sólo cuando necesites:
- El **scope original** de una feature antes de que aterrizara (para
  entender qué se prometía vs qué se entregó).
- La **timeline de decisiones** de un tema (los archivos tienen
  fechas en el nombre).
- **Evidencia histórica** de por qué el equipo eligió X over Y en una
  conversación pasada.

Para cualquier otra cosa: lee `docs/ESTADO-Y-GAPS.md` directamente.
