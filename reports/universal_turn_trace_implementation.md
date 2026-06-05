# Implementacion Universal Turn Trace

Fecha: 2026-06-04
Decision: `UNIVERSAL_TURN_TRACE_READY`

## Alcance

Se implemento Prompt 4: una vista universal de auditoria para cada turno del `agent_runtime_v2`.

No se activo trafico real, no se aplico configuracion Dinamo a base de datos, no se envio WhatsApp real, no se habilitaron actions/workflows reales y no se modifico frontend.

## Archivos creados

- `core/atendia/agent_runtime/universal_turn_trace.py`
- `core/tests/agent_runtime/test_universal_turn_trace.py`
- `reports/universal_turn_trace_implementation.md`
- `reports/universal_turn_trace_implementation.json`

## Archivos modificados

- `core/atendia/agent_runtime/advisor_pipeline.py`
- `core/atendia/agent_runtime/__init__.py`

## Contrato implementado

La vista se adjunta en `TurnOutput.trace_metadata["universal_turn_trace"]` con `trace_version="1.0"` y conserva la traza cruda existente.

Secciones incluidas:

- `input`
- `gpt_understanding`
- `gpt_proposed`
- `mandatory_tool_decisions`
- `tool_results`
- `atendia_validation`
- `state_changes`
- `lifecycle`
- `business_events`
- `workflow_results`
- `guards`
- `provider`
- `final_output`
- `audit`

## Separacion GPT vs AtendIA

`gpt_proposed` contiene propuestas del `AdvisorBrainDecision`: cambios de estado, lifecycle y herramientas requeridas.

`atendia_validation` contiene la validacion deterministica: decisiones de mandatory tools, decisiones del StateWriter, guards, policy warnings y safe mode.

## Final output

`final_output.final_message` usa exclusivamente `TurnOutput.final_message` y declara:

- `source="TurnOutput.final_message"`
- `visible=true`
- `visible_to_customer=true`

Las herramientas siguen sin permiso para devolver copia visible.

## Tool trace

Cada tool result se proyecta como estructura interna:

- `tool_id`
- `status`
- `tenant_id`
- `safe_inputs`
- `structured_output`
- `citations`
- `used_for`
- `visible_text_allowed=false`
- `error`
- `trace_metadata`

El schema existente `ToolExecutionResult` sigue rechazando `final_message`, `message` y `reply` dentro de `data`.

## Guards

La vista normaliza resultados de guards a:

- `passed`
- `warned`
- `blocked`
- `rewrote`

La traza cruda queda intacta. La vista universal compacta detalles de guards para no renderizar campos de otro dominio en tenants que no los usan.

## Lifecycle, eventos y workflows

`lifecycle` expone `stage_before`, `status_before`, `stage_proposed`, `status_proposed`, `stage_after`, `status_after`, `proposed_updates` y `validated_update`; si no hay dato, queda `null`.

`business_events` y `workflow_results` quedan como arrays vacios cuando no existen. No se ejecutan workflows.

## Safe mode y tenant isolation

`audit.safe_mode` y `atendia_validation.safe_mode` reflejan `context.tenant_config.safe_mode`.

El test de tenant de citas valida que la vista universal no renderiza campos de vehiculo (`product_selection`, `plan_selection`, `quote_snapshot_id`) ni el tenant fixture de otro dominio.

## Helper de explicacion

Se agrego `why_answer_from_universal_trace(trace)` para una explicacion no tecnica y sin detalles sensibles. No sustituye la autoridad de copia visible.

## Tests ejecutados

```text
uv run ruff check atendia/agent_runtime/universal_turn_trace.py atendia/agent_runtime/advisor_pipeline.py atendia/agent_runtime/schemas.py tests/agent_runtime/test_universal_turn_trace.py
Resultado: All checks passed.
```

```text
uv run pytest tests/agent_runtime/test_universal_turn_trace.py tests/agent_runtime/test_declarative_state_writer.py tests/agent_runtime/test_mandatory_tool_contract.py tests/agent_runtime/test_tenant_domain_contract.py -q
Resultado: 37 passed, 1 warning.
```

```text
uv run pytest tests/agent_runtime -m "not integration_db" -q
Resultado: 179 passed, 27 deselected, 2 warnings.
```

Warnings observados:

- `PytestCacheWarning` por falta de permisos para escribir `.pytest_cache`.
- `UserWarning` preexistente en `contracts/tone.py` por shadowing de `register`.

## Riesgos residuales

- La suite `integration_db` no se ejecuto porque requiere base de datos de pruebas configurada.
- La vista universal es una proyeccion de auditoria; consumidores nuevos deben leer `trace_metadata["universal_turn_trace"]` sin reemplazar la traza cruda.
