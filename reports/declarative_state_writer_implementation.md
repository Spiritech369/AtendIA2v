# Implementacion StateWriter declarativo

Fecha: 2026-06-03
Decision: `DECLARATIVE_STATE_WRITER_READY`

## Alcance

Se implemento Prompt 3: StateWriter declarativo por `field_metadata` del `tenant_domain_contract`.

No se activo trafico real, no se aplico configuracion Dinamo a base de datos, no se envio WhatsApp real, no se habilitaron actions/workflows reales y no se modifico frontend.

## Archivos creados

- `core/tests/agent_runtime/test_declarative_state_writer.py`
- `reports/declarative_state_writer_implementation.md`
- `reports/declarative_state_writer_implementation.json`

## Archivos modificados

- `core/atendia/agent_runtime/state_writer.py`
- `core/atendia/agent_runtime/tenant_domain_contract.py`
- `core/atendia/agent_runtime/advisor_pipeline.py`
- `core/tests/agent_runtime/fixtures/tenant_domain_contracts/vehicle_credit_sales.json`
- `core/tests/agent_runtime/fixtures/tenant_domain_contracts/appointment_services.json`

## Policies soportadas

- `auto_apply`
- `auto_apply_when_explicit`
- `auto_apply_when_catalog_match`
- `auto_apply_when_valid_plan`
- `suggest_review`
- `tool_only`
- `blocked_from_model`
- `attachment_required`
- `system_derived`

## Integracion con tenant_domain_contract

`StateWriter` ahora lee:

- `context.tenant_config.field_metadata`
- `context.tenant_config.safe_mode`
- aliases declarados por campo
- `write_policy`
- `allowed_sources`
- `evidence_required`
- `domain_role`
- `invalidates_roles`
- `invalidates_fields`
- `required_tools`
- `value_path`

Si `safe_mode=true`, bloquea escrituras propuestas por modelo y registra `safe_mode_blocks_field_write`.

Si existe `field_metadata`, un campo no declarado en el contrato queda bloqueado con `field_not_declared_in_tenant_contract`. Esto evita que un tenant no-Dinamo acepte campos de otro dominio por fallback legacy.

## Aliases

Los aliases se resuelven desde metadata del campo. Ejemplos en fixtures:

- `MOTO`, `MODELO_INTERES`, `product`, `model` -> `product_selection`
- `CREDITO`, `PLAN`, `PLAN_CREDITO` -> `plan_selection`
- `quote_snapshot`, `ULTIMA_COTIZACION` -> `quote_snapshot_id`
- `Doc_Completos`, `docs_complete` -> `requirements_complete`
- `service`, `servicio` -> `service_selection`

No se agregaron aliases de Dinamo al core; viven en fixtures/config.

## Escrituras sensibles

Reglas implementadas:

- `tool_only` no acepta propuestas GPT.
- `blocked_from_model` no acepta propuestas GPT.
- `system_derived` no acepta propuestas GPT.
- `attachment_required` requiere adjunto, review humana, vision/document checker o tool equivalente.
- `auto_apply_when_catalog_match` requiere `catalog.search` confiable.
- `auto_apply_when_valid_plan` requiere resolver plan o valor permitido explicito.
- `suggest_review` queda en `needs_review` sin escritura definitiva.
- Tool results cruzados de otro tenant no cuentan como evidencia.
- `requirements_complete` exige `requirements.lookup` + `document.check` en fixture.

## Quote invalidation

Campos con `domain_role` `selection` o `plan`, o metadata `invalidates_roles=["quote"]`, invalidan campos `domain_role="quote"` cuando cambia el valor guardado.

Ejemplo:

- cambia `product_selection`
- se invalida `quote_snapshot_id`

El resultado aparece como `FieldUpdate(value=None)` con metadata:

- `quote_snapshot_invalidated`
- `invalidated_by_field_change`
- `changed_field`
- `invalidated_field`

## Trace metadata

`advisor_pipeline.py` ahora agrega:

```json
{
  "state_writer_decisions": [],
  "state_writer_summary": {
    "accepted_count": 0,
    "blocked_count": 0,
    "needs_review_count": 0,
    "invalidated_count": 0,
    "safe_mode": false
  },
  "invalidated_fields": []
}
```

`state_writer.accepted` y `state_writer.blocked` conservan el formato legacy para no romper pruebas existentes. La vista detallada nueva vive en `state_writer_decisions`.

## Tests ejecutados

```bash
uv run ruff check atendia/agent_runtime/state_writer.py atendia/agent_runtime/tenant_domain_contract.py tests/agent_runtime/test_declarative_state_writer.py
```

Resultado:

```text
All checks passed!
```

```bash
uv run pytest tests/agent_runtime/test_declarative_state_writer.py tests/agent_runtime/test_tenant_domain_contract.py tests/agent_runtime/test_mandatory_tool_contract.py -q
```

Resultado:

```text
28 passed, 1 warning in 0.33s
```

```bash
uv run pytest tests/agent_runtime -m "not integration_db" -q
```

Resultado:

```text
170 passed, 27 deselected, 2 warnings in 2.90s
```

```bash
uv run pytest tests/agent_runtime -q
```

Resultado:

```text
blocked: integration_db tests require ATENDIA_TEST_DATABASE_URL
```

## Riesgos restantes

- Falta conectar frontend a `state_writer_decisions`, `needs_review` e invalidaciones.
- Falta persistir propuestas `needs_review` como entidad operativa revisable.
- La politica de `auto_apply_when_valid_plan` puede necesitar catalogo de planes tenant-scoped mas rico.
- La invalidacion de quote ya es declarativa por roles/campos, pero faltan pruebas de UI y workflows aguas abajo.
- Tests `integration_db` no corrieron porque no estaba configurado `ATENDIA_TEST_DATABASE_URL`.

## Siguiente paso recomendado

Implementar Prompt 4: `universal_turn_trace`, usando `state_writer_decisions`, `mandatory_tool_decisions`, guards y business events como narrativa operacional.
