# PHASE_CHECKPOINT_PRODUCT_FIRST_BASELINE

Date: 2026-06-07

## Purpose

Document the current Product-First baseline before adding more code.

This checkpoint is not a commit, not a reset, not a cleanup, and not a live
activation. It only records what is currently ready, which files belong to the
Product-First baseline, and what remains unsafe or dirty in the worktree.

## Current Decision Baseline

- `SPEC_KIT_PRODUCT_FIRST_PLAN_READY`
- `PRODUCT_FIRST_IMPLEMENTATION_BACKLOG_READY`
- `PRODUCT_ENTITIES_FOUNDATION_READY`
- `AGENT_BUILDER_MVP_READY`
- `KNOWLEDGE_SOURCES_PRODUCTIZED_READY`

## Product-First Baseline Ready

### Phase 0/1 - Product-First Architecture Alignment

Ready:

- Canonical architecture authority established.
- `Arquitectura-Deseada.md` is canonical for Product-First transformation.
- `ARCHITECTURE.md` remains stable system summary.
- `AGENTS.md` remains Codex operational rulebook.
- `docs/architecture/` contains current contracts.
- `reports/` contains historical evidence.

### Phase 2 - Product Entities Foundation

Ready:

- Product Agent control-plane models and services exist.
- Product Agent entities are tenant-scoped.
- Agent versions are versioned and immutable after publish.
- Deployments keep send/live/outbox/action/workflow flags safe by default.
- Bindings exist for knowledge, tools, actions, fields, and workflows.
- Product Entities tests exist and pass in the Product Agents suite.

### Phase 3 - Agent Builder MVP

Ready:

- `/api/v1/product-agents` Product-First API exists.
- `/agent-builder` frontend route exists.
- Agent list/create works against Product-First API.
- Draft version creation and editing exist.
- Identity, prompt block, safety view, and readiness view exist.
- Legacy Agents API is not used by Agent Builder.
- No live/runtime/send/outbox/workflow behavior is activated.

### Phase 4 - Knowledge Sources Productized

Ready:

- Knowledge Source options are exposed tenant-scoped.
- Agent draft Knowledge Source bindings can be listed.
- Agent draft Knowledge Source bindings can be created.
- Agent draft Knowledge Source bindings can be removed.
- Agent-scoped readiness includes source binding health.
- Readiness blocks missing knowledge sources.
- Readiness blocks unhealthy knowledge sources.
- Readiness keeps `test_lab_passed=false`.
- Readiness keeps `live_publish_allowed=false`.
- Agent Builder has a `Knowledge` tab.
- Knowledge tab shows available sources, connected sources, health, status,
  checksum/version, last indexed timestamp, redacted errors, blockers, bind,
  and unbind.
- UI does not claim WhatsApp/live/publish is active.

## Product-First Files In Baseline

These files are part of the Product-First baseline and currently appear as
untracked in this dirty worktree because the broader Product-First work has not
been committed or staged.

### Backend

- `core/atendia/api/product_agents_routes.py`
- `core/atendia/product_agents/__init__.py`
- `core/atendia/product_agents/schemas.py`
- `core/atendia/product_agents/service.py`
- `core/atendia/db/migrations/versions/066_product_first_agent_entities.py`
- `core/atendia/db/models/product_agent.py`

### Backend Tests

- `core/tests/product_agents/test_action_binding_permissions.py`
- `core/tests/product_agents/test_agent_builder_api_routes.py`
- `core/tests/product_agents/test_agent_builder_service.py`
- `core/tests/product_agents/test_agent_deployment_publish_state_machine.py`
- `core/tests/product_agents/test_agent_entities_no_dinamo_hardcode.py`
- `core/tests/product_agents/test_agent_knowledge_binding_productized_service.py`
- `core/tests/product_agents/test_agent_knowledge_binding_same_tenant_required.py`
- `core/tests/product_agents/test_agent_model_tenant_scoped.py`
- `core/tests/product_agents/test_agent_readiness_blocks_unhealthy_knowledge.py`
- `core/tests/product_agents/test_agent_readiness_blocks_without_knowledge.py`
- `core/tests/product_agents/test_agent_readiness_passes_knowledge_connected_not_publish.py`
- `core/tests/product_agents/test_agent_version_immutable_after_publish.py`
- `core/tests/product_agents/test_knowledge_binding_no_dinamo_hardcode.py`
- `core/tests/product_agents/test_knowledge_source_binding_requires_existing_source.py`
- `core/tests/product_agents/test_product_agents_api_routes.py`
- `core/tests/product_agents/test_product_agent_knowledge_source_options_tenant_scoped.py`
- `core/tests/product_agents/test_product_agent_service_repository.py`
- `core/tests/product_agents/test_publish_state_does_not_enable_live_send.py`
- `core/tests/product_agents/test_tool_binding_schema_validation.py`

### Frontend

- `frontend/src/features/product-agent-builder/api.ts`
- `frontend/src/features/product-agent-builder/components/AgentBuilderPage.tsx`
- `frontend/src/routes/(auth)/agent-builder.tsx`
- `frontend/src/features/navigation/menu-config.ts`
- `frontend/src/routeTree.gen.ts`

### Frontend Tests

- `frontend/tests/features/product-agent-builder/AgentBuilderPage.test.tsx`

### Product-First Architecture And Specs

- `Arquitectura-Deseada.md`
- `ARCHITECTURE.md`
- `AGENTS.md`
- `.specify/`
- `specs/001-product-first-agent-platform/`
- `docs/architecture/atendia_agent_builder_contract.md`
- `docs/architecture/atendia_agent_runtime_sdk_contract.md`
- `docs/architecture/decisions/`
- `docs/architecture/feature_readiness_matrix.md`
- `docs/architecture/legacy_deprecation_plan.md`
- `docs/architecture/product_first_acceptance_tests.md`
- `docs/architecture/product_first_action_registry.md`
- `docs/architecture/product_first_agent_builder.md`
- `docs/architecture/product_first_controlled_beta_dinamo.md`
- `docs/architecture/product_first_definition_of_done.md`
- `docs/architecture/product_first_definition_of_ready.md`
- `docs/architecture/product_first_implementation_backlog.md`
- `docs/architecture/product_first_inbox_trace_ux.md`
- `docs/architecture/product_first_knowledge_sources.md`
- `docs/architecture/product_first_legacy_isolation.md`
- `docs/architecture/product_first_product_entities.md`
- `docs/architecture/product_first_publish_control.md`
- `docs/architecture/product_first_runtime_single_route.md`
- `docs/architecture/product_first_test_lab.md`
- `docs/architecture/product_first_workflow_bindings.md`
- `docs/product/agent_builder_product_spec.md`
- `docs/product/agent_publish_control_spec.md`
- `docs/product/agent_test_lab_spec.md`

### Product-First Reports

- `reports/product_entities_foundation_2026_06_07.md`
- `reports/product_first_phase_3_agent_builder_2026_06_07.md`
- `reports/product_first_phase_4_knowledge_sources_productized_2026_06_07.md`
- `reports/product_first_implementation_backlog_2026_06.md`
- `reports/spec_kit_source_alignment_2026_06.md`

## Generated Noise To Preserve For Now

The following generated files exist because tests were run. They were not
deleted because this checkpoint explicitly avoids cleanup/destructive actions:

- `core/atendia/product_agents/__pycache__/`
- `core/tests/product_agents/__pycache__/`

These are not part of the architectural baseline. They should be removed only
after explicit cleanup approval.

## Worktree Status

Observed with `git status --short | Measure-Object`:

- Total dirty entries: 419

Important interpretation:

- The repository is not in a clean git state.
- The Product-First baseline files above are currently untracked or modified.
- There are many pre-existing deletes/modifications outside the Product-First
  baseline.
- No reset, restore, checkout, clean, delete, or staging was performed.

## Verification Baseline

Latest executed verification for Product-First Product Agents and Agent Builder:

- `uv run ruff check atendia/product_agents atendia/api/product_agents_routes.py tests/product_agents`
  - Result: passed.
- `uv run pytest tests/product_agents -q --cov=atendia.product_agents --cov=atendia.api.product_agents_routes --cov-report=term-missing --cov-fail-under=100`
  - Result: 70 passed, 100% coverage.
- `npm.cmd exec -- biome check src/features/product-agent-builder tests/features/product-agent-builder`
  - Result: passed.
- `npm.cmd run test -- AgentBuilderPage.test.tsx --run --coverage --coverage.include="src/features/product-agent-builder/**/*.{ts,tsx}" --coverage.reporter=text --coverage.thresholds.lines=100 --coverage.thresholds.functions=100 --coverage.thresholds.branches=100 --coverage.thresholds.statements=100`
  - Result: 11 passed, 100% statements/branches/functions/lines.
- `npm.cmd run build`
  - Result: passed.
- Scoped `git diff --check`
  - Result: passed.
- Security searches for tenant hardcode and live true flags in Product-First
  modified code
  - Result: no matches.

## Live Safety Baseline

Confirmed by scope and verification:

- No WhatsApp activation.
- No smoke activation.
- No canary activation.
- No production activation.
- No SendAdapter changes.
- No outbox behavior changes.
- No workflow/action side effects.
- No Runtime V2 live behavior change.
- No tenant-specific Dinamo/motos/credit hardcode in Product-First generic code.

## Open Risk

- Worktree has 419 dirty entries.
- Product-First baseline is not committed or staged.
- Untracked generated `__pycache__` files exist after test runs.
- Many unrelated deletes/modifications appear to predate this checkpoint and
  must not be reverted without explicit user approval.
- Next implementation should start only after deciding whether to:
  - keep working in this dirty baseline,
  - stage/commit Product-First baseline,
  - create an explicit cleanup plan,
  - or split into a fresh branch/worktree.

## Checkpoint Decision

`PHASE_CHECKPOINT_PRODUCT_FIRST_BASELINE`
