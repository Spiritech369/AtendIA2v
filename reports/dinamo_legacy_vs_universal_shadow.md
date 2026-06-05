# Dinamo Legacy vs Universal Shadow

Decision: `legacy fallback necesario`

Generated at: `2026-06-03T22:24:52.1570446-06:00`

## Comparison

The legacy runner remains the production fallback. Prompt 7 did not replace live routing or production traffic.

| Area | Legacy | Universal shadow |
| --- | --- | --- |
| Visible response | Current production authority | `TurnOutput.final_message` in preview |
| Facts | May depend on existing legacy composition | Requires mandatory tools for price, requirements, and policy facts |
| Fields written | Existing runtime path | Declarative StateWriter accepts/blocks by tenant field policy |
| Pipeline | Existing legacy state flow | Shadow lifecycle changes: `plan_identificado`, `cotizado`, `papeleria_solicitada`, `papeleria_recibida`, `en_revision_humana` |
| Workflows | Legacy behavior unchanged | Business events only, workflow results dry-run |
| Guards | Existing safeguards | MandatoryToolGuard plus tenant-declared guard metadata in trace |
| Tool usage | Existing tool/runtime behavior | Tool results are structured, tenant-scoped, and cannot return visible final copy |
| Risk of incoherence | Production fallback remains necessary until shadow eval is reviewed | Lower for tested scenario because GPT proposals are separated from AtendIA validation |

## Per-Turn Decision

- Turn 1: universal shadow better for traceability; legacy fallback still necessary for production.
- Turn 2: universal shadow better for quote integrity because response uses `quote.resolve` snapshot.
- Turn 3: universal shadow better for requirements isolation because `requirements.lookup` is mandatory.
- Turn 4: universal shadow better for state hygiene because future intent does not mark document received.
- Turn 5: universal shadow better for partial document state because `document.check` emits dry-run events.
- Turn 6: universal shadow better for handoff traceability because human review is dry-run and no approval is promised.

## Decision

Universal shadow is better for the tested path, but legacy fallback remains necessary. Do not replace production runner until real replay, human approval, and rollback gates are complete.
