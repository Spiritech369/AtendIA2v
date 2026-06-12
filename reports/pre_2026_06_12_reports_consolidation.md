# Pre 2026-06-12 Reports Consolidation

Fecha: 2026-06-12

Alcance: auditoria de `reports/` excluyendo reportes creados o nombrados con
`2026_06_12` / `2026-06-12`.

## Resultado ejecutivo

Se revisaron 262 archivos previos al 12 de junio. La limpieza segura identificada
fue consolidar y eliminar las corridas granulares del simulador manual:
`manual_live_simulator_run_*`.

No se eliminaron incidentes, gates, reportes referenciados por specs, ni evidencia
runtime relevante. Esos reportes siguen funcionando como trazabilidad historica,
evidencia de rollback, aprobaciones o pruebas de seguridad.

## Inventario revisado

| Grupo | Archivos | Peso aprox. | Decision |
| --- | ---: | ---: | --- |
| Corridas manuales del simulador | 188 | 2881.6 KB | Consolidar y eliminar |
| Product-First planning | 19 | 71.4 KB | Conservar por ahora |
| Respond style evidence | 21 | 269.2 KB | Conservar por ahora |
| Runtime/test/shadow evidence | 17 | 368.3 KB | Conservar |
| Smoke/activation/incidents | 12 | 290.3 KB | Conservar |
| Otros | 5 | 24.7 KB | Conservar por ahora |

## Archivos eliminados por esta limpieza

Se eliminaron solamente archivos que cumplen todas estas condiciones:

- Estan bajo `reports/`.
- Su nombre empieza con `manual_live_simulator_run_`.
- No son del 12 de junio.
- No aparecieron referenciados fuera de `reports/`.
- Son evidencia granular reemplazada por reportes de fases, ventanas y gates
  posteriores.

Detalle por grupo:

| Grupo | JSON | MD | Total |
| --- | ---: | ---: | ---: |
| 2026_06_09 | 11 | 11 | 22 |
| r2 | 10 | 10 | 20 |
| r3 | 10 | 10 | 20 |
| r4 | 10 | 10 | 20 |
| r5mini | 10 | 10 | 20 |
| r5o | 10 | 10 | 20 |
| r6o | 10 | 10 | 20 |
| r7o | 10 | 10 | 20 |
| r8o | 10 | 10 | 20 |
| r9o | 1 | 1 | 2 |
| r10o | 2 | 2 | 4 |
| Total | 94 | 94 | 188 |

Patron eliminado:

```text
reports/manual_live_simulator_run_2026_06_09_*.json
reports/manual_live_simulator_run_2026_06_09_*.md
reports/manual_live_simulator_run_2026_06_10_*_r*.json
reports/manual_live_simulator_run_2026_06_10_*_r*.md
```

## Reportes que aportan al estado actual

Conservar estos reportes porque todavia tienen valor operativo, historico o de
trazabilidad:

- `controlled_single_contact_smoke_v2_incident_2026_06_08.md`
- `controlled_single_contact_smoke_v3_incident_2026_06_08.md`
- `controlled_single_contact_smoke_v3_retry_activation_2026_06_09.md`
- `human_response_composer_from_validated_facts_2026_06_08.md`
- `live_simulated_channel_no_send_2026_06_09.md`
- `live_transcript_replay_gate_2026_06_09.md`
- `product_agent_runtime_direct_no_send_2026_06_09.md`
- `respond_style_context_builder_no_send_2026_06_09.md`
- `respond_style_phase_0_5_amended_no_send_2026_06_09.md`
- `respond_style_phase_10_fixes_and_test_lab_direct_2026_06_09.md`
- `respond_style_phase_11_multiround_testlab_resolver_2026_06_09.md`
- `respond_style_phase_12_docker_e2e_hard_block_2026_06_09.md`
- `respond_style_phase_13_publish_shadow_parity_2026_06_09.md`
- `spec_kit_source_alignment_2026_06.md`

Estos archivos aparecen referenciados fuera de `reports/` o describen incidentes,
gates, pruebas de no-send, shadow/live readiness o decisiones que no deben perderse.

## Candidatos para una segunda limpieza

No se tocaron en esta pasada por riesgo de trazabilidad:

- Product-First phase reports: muchos ya estan superados por `Arquitectura-Deseada.md`,
  `docs/architecture/` y `specs/001-product-first-agent-platform/`.
- Respond-style phase reports antiguos: varios pueden consolidarse, pero primero
  conviene mapearlos contra fases actuales y referencias externas.
- JSON result blobs con par `.md`: algunos podrian eliminarse si el `.md` conserva
  suficiente evidencia y ningun script los consulta.
- Approval packets previos a incidentes: pueden archivarse, pero los incidentes y
  rollbacks deben conservarse.

## Invariantes respetados

- No se modifico codigo runtime.
- No se tocaron rutas live, smoke, canary, outbox ni WhatsApp send.
- No se eliminaron incidentes.
- No se eliminaron reportes referenciados por specs/docs/scripts.
- No se tocaron reportes del 12 de junio.
- La limpieza es reversible desde git.

## Verificacion recomendada

Despues del borrado:

```powershell
Get-ChildItem reports -File | Where-Object { $_.Name -like 'manual_live_simulator_run_*' }
git status --short reports
rg -n "manual_live_simulator_run_" .
```

El primer comando debe devolver cero archivos. El segundo debe mostrar este
documento y las eliminaciones. El tercero no debe encontrar referencias runtime
criticas a los archivos eliminados.
