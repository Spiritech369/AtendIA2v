# AtendIA Codex Notes

- Do not hardcode a vertical, Dinamo, motos, credit rules, or tenant documents inside `agent_runtime_v2`.
- Prefer tenant configuration and tenant-scoped data over global assumptions.
- Keep one authority for customer-facing final copy: `TurnOutput.final_message`.
- Tools and actions return structured data, not final visible response text.
- Keep the legacy runner as fallback until the migration is complete and evaluated.
- Every behavioral change should include focused tests.
- Preserve traceability, auditability, and tenant isolation in all runtime changes.
