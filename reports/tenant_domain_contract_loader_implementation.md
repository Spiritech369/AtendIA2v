# Implementacion tenant_domain_contract_loader

Fecha: 2026-06-03
Decision: `TENANT_DOMAIN_CONTRACT_LOADER_READY`

## Alcance

Se implemento Prompt 2: loader y validador versionado de `tenant_domain_contract` para `agent_runtime_v2`.

No se activo trafico real, no se envio WhatsApp, no se aplico configuracion Dinamo a base de datos, no se habilitaron actions/workflows reales y no se modifico frontend.

## Archivos creados

- `core/atendia/agent_runtime/tenant_domain_contract.py`
- `core/tests/agent_runtime/test_tenant_domain_contract.py`
- `core/tests/agent_runtime/fixtures/tenant_domain_contracts/vehicle_credit_sales.json`
- `core/tests/agent_runtime/fixtures/tenant_domain_contracts/appointment_services.json`
- `reports/tenant_domain_contract_loader_implementation.md`
- `reports/tenant_domain_contract_loader_implementation.json`

## Archivos modificados

- `core/atendia/agent_runtime/schemas.py`
- `core/atendia/agent_runtime/context_builder.py`
- `core/atendia/agent_runtime/mandatory_tools.py`
- `core/atendia/agent_runtime/advisor_pipeline.py`
- `core/atendia/agent_runtime/__init__.py`

## Schema implementado

Se agrego `TenantDomainContract` versionado con:

- `contract_version`
- `tenant_id`
- `agent_id`
- `domain`
- `locale`
- `timezone`
- `entities`
- `fields`
- `tools`
- `pipeline`
- `workflow_events`
- `guards`
- `frontend`
- `trace`
- `safety`
- `safe_mode`

Dominios soportados:

- `vehicle_credit_sales`
- `appointment_services`
- `generic_lead_qualification`

El loader valida version, dominio soportado, tenant isolation y unicidad de fields/tools. Si falta contrato o es invalido, cae a safe mode con dominio `generic_lead_qualification`, fields/tools vacios y guards minimos `mandatory_tool_guard` y `final_copy_guard`.

## Fixtures creados

Fixture `vehicle_credit_sales`:

- Tenant: `tenant_dinamo_fixture`
- Agent: `agent_francisco_fixture`
- Fields: `product_selection`, `plan_selection`, `quote_snapshot_id`, `requirements_complete`
- Tools: `catalog.search`, `quote.resolve`, `requirements.lookup`, `faq.lookup`, `document.check`

Fixture `appointment_services`:

- Tenant: `tenant_barber_fixture`
- Agent: `agent_barber_fixture`
- Fields: `service_selection`, `appointment_time`, `booking_status`
- Tools: `catalog.search`, `availability.check`, `booking.create`, `faq.lookup`

## Integracion con ContextBuilder

`ContextBuilder` ahora carga el contrato desde:

- `metadata.tenant_domain_contract`
- `metadata.domain_contract`
- `metadata.tenant_config.tenant_domain_contract`
- `metadata.tenant_config.domain_contract`
- `tenant_config` dentro de `agent_runtime_v2` cuando hay DB session
- `runtime_config.tenant_domain_contract`
- `runtime_config.domain_contract`

El runtime context expone:

- `tenant_config.tenant_domain_contract`
- `tenant_config.domain`
- `tenant_config.field_metadata`
- `tenant_config.tool_metadata`
- `tenant_config.pipeline_metadata`
- `tenant_config.workflow_event_metadata`
- `tenant_config.guard_metadata`
- `tenant_config.frontend_metadata`
- `tenant_config.safe_mode`

Tambien agrega metadata de contexto/trace:

```json
{
  "tenant_domain_contract": {
    "version": "1.0",
    "domain": "vehicle_credit_sales",
    "safe_mode": false
  },
  "field_metadata_loaded": true,
  "tool_metadata_loaded": true,
  "pipeline_metadata_loaded": true,
  "guard_metadata_loaded": true
}
```

En safe mode incluye razon, por ejemplo `missing_contract`.

## Integracion con MandatoryToolGuard

El contrato inyecta reglas declarativas en `tenant_config.ruleset.mandatory_tools.rules`.

`MandatoryToolGuard` ahora usa:

- reglas universales default
- reglas derivadas del tenant/domain contract
- aliases de tools declarados por tenant
- metadata de tools por tenant
- tenant isolation en tool results

Reglas cubiertas:

- Precio/pago/descuento/vigencia requiere quote tool.
- Requisitos/documentos requiere requirements tool.
- Politica sensible requiere FAQ/policy tool.
- Documento recibido/completo requiere document tool.
- Disponibilidad/cita requiere availability tool.
- Reserva/cita confirmada requiere booking tool.

## Tests ejecutados

```bash
uv run ruff check atendia/agent_runtime/tenant_domain_contract.py atendia/agent_runtime/mandatory_tools.py atendia/agent_runtime/context_builder.py tests/agent_runtime/test_tenant_domain_contract.py tests/agent_runtime/test_mandatory_tool_contract.py
```

Resultado:

```text
All checks passed!
```

```bash
uv run pytest tests/agent_runtime/test_tenant_domain_contract.py tests/agent_runtime/test_mandatory_tool_contract.py tests/agent_runtime/test_agent_runtime_v2.py -q
```

Resultado:

```text
33 passed, 2 warnings in 1.69s
```

Warnings:

- `Tone.register` shadows BaseModel attribute.
- Pytest cache path permission warning.

```bash
uv run pytest tests/agent_runtime -q
```

Resultado:

```text
Exit: integration_db tests require ATENDIA_TEST_DATABASE_URL
```

Esto no fue una falla funcional del cambio; faltaba la DB de integracion.

```bash
uv run pytest tests/agent_runtime -m "not integration_db" -q
```

Resultado:

```text
157 passed, 27 deselected, 2 warnings in 1.89s
```

## Validaciones adicionales

Se busco `Dinamo`, `dinamo`, `motos`, `moto` y `credito` en archivos core tocados. Solo aparecieron menciones en tests/fixtures, no en core.

## Riesgos restantes

- Falta conectar persistencia real de contratos en DB con migracion/administracion.
- Frontend aun no consume `field_metadata`, `tool_metadata` ni trace nuevo.
- Workflows aun no leen business events desde este contrato.
- Las reglas derivadas son conservadoras; algunos tenants requeriran tuning declarativo.
- Los tests de DB no corrieron porque no estaba configurado `ATENDIA_TEST_DATABASE_URL`.

## Siguiente paso recomendado

Implementar Prompt 3: StateWriter declarativo por field policies del tenant/domain contract.
