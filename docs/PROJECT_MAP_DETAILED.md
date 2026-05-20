# AtendIA v2 - Detailed Project Map

Last manual update: 2026-05-20.

This document is the implementation map for the repo. It explains where each
runtime piece lives and how the configurable tenant model is wired. The current
priority is to keep the platform reusable: no single vertical should own the
Python code path when the behavior can be represented as tenant configuration,
Knowledge Base evidence, customer fields, pipeline rules or agent prompts.

## Mental Model

AtendIA v2 has five layers:

1. Backend runtime: API, webhooks, auth, DB, workers and realtime.
2. Frontend workspace: operator UI, tenant config, pipeline, Knowledge Base and traces.
3. Tenant configuration: fields, pipeline, docs, agents, branding, channels and QoS.
4. AI turn runtime: NLU, flow router, tools/evidence, composer, deterministic guards.
5. Observability: messages, system events, turn traces, attachments and workflow events.

## End-To-End Message Flow

1. WhatsApp inbound arrives through Meta or Baileys.
   - Meta: `core/atendia/webhooks/meta_routes.py`
   - Baileys: `core/atendia/api/baileys_routes.py`, `core/baileys-bridge/`
2. The backend stores or updates customer, conversation and message rows.
   - `core/atendia/api/conversations_routes.py`
   - `core/atendia/db/models/conversation.py`
3. The runner processes the turn.
   - `core/atendia/runner/conversation_runner.py`
4. NLU extracts intent and configured customer fields.
   - `core/atendia/runner/nlu_prompts.py`
   - `core/atendia/runner/nlu_openai.py`
   - `core/atendia/runner/ai_extraction_service.py`
5. The flow router selects PLAN, SALES, DOC, OBSTACLE, RETENTION or SUPPORT.
   - `core/atendia/runner/flow_router.py`
6. Pipeline rules evaluate whether the stage should move.
   - `core/atendia/state_machine/pipeline_evaluator.py`
   - `core/atendia/state_machine/pipeline_loader.py`
7. Tools and retrieval provide evidence.
   - Catalog: `core/atendia/tools/search_catalog.py`
   - Requirements: `core/atendia/tools/lookup_requirements.py`
   - RAG: `core/atendia/tools/rag/`
   - Vision: `core/atendia/tools/vision.py`
8. Composer writes the customer-facing response.
   - `core/atendia/runner/composer_prompts.py`
   - `core/atendia/runner/composer_openai.py`
9. Sensitive output is guarded deterministically where required.
   - Structured quotes: `conversation_runner.py`
   - Docs complete: `pipeline_evaluator.py`
10. Outbound messages are stored and sent through workers.
   - `core/atendia/runner/outbound_dispatcher.py`
   - `core/atendia/queue/outbox.py`
   - `core/atendia/queue/worker.py`
11. Realtime and debug surfaces update the frontend.
   - `core/atendia/realtime/`
   - `core/atendia/db/models/turn_trace.py`
   - `frontend/src/features/turn-traces/`

## Backend Map

### `core/atendia/api/`

HTTP routes and feature APIs.

- `auth_routes.py`: login, logout, session.
- `conversations_routes.py`: inbox, conversation details, messages, attachments,
  customer fields and required-doc checklist.
- `customers_routes.py`: customer CRM profile and attrs.
- `customer_fields_routes.py`: tenant-defined customer fields and per-customer values.
- `pipeline_routes.py`: pipeline editor, kanban, versioning and movements.
- `tenants_routes.py`: tenant config, prompt modes, pipeline history and branding.
- `agents_routes.py`: agent config, preview, versioning and publishing.
- `knowledge_routes.py`, `_kb/*`: Knowledge Base CRUD, search, command center and tests.
- `integrations_routes.py`: Meta/Baileys config.
- `baileys_routes.py`: internal Baileys bridge API.
- `turn_traces_routes.py`: debug traces by turn.
- `workflows_routes.py`: workflow editor and executions.
- `handoffs_routes.py`: human handoff surfaces.

### `core/atendia/runner/`

The AI runtime.

- `conversation_runner.py`: central orchestration for a turn.
- `nlu_protocol.py`, `nlu_prompts.py`, `nlu_openai.py`: extraction/classification.
- `composer_protocol.py`, `composer_prompts.py`, `composer_openai.py`: response composition.
- `flow_router.py`: mode routing.
- `ai_extraction_service.py`: applies extracted fields to customer attrs/field values.
- `field_extraction_mapping.py`: canonical field mapping.
- `vision_to_attrs.py`: maps Vision results into `DOCS_*` customer attrs.
- `conversation_events.py`: creates system events/stage events.
- `outbound_dispatcher.py`: persists and enqueues outbound messages.
- `followup_scheduler.py`: follow-up scheduling.

### `core/atendia/state_machine/`

Pipeline and rule evaluation.

- `pipeline_loader.py`: loads the active tenant pipeline.
- `pipeline_evaluator.py`: evaluates `auto_enter_rules`, including
  `docs_complete_for_plan`.
- `orchestrator.py`: state-machine orchestration.
- `conditions.py`, `transitioner.py`, `action_resolver.py`: supporting pipeline logic.
- `motos_credito_pipeline.json`: seed/reference pipeline, not a hardcoded runtime contract.

### `core/atendia/config_validation.py`

Central validator for tenant-authored configuration. It is called before saving
pipeline/docs configuration and by agent validation. It catches:

- `docs_ine_frente` style legacy/lowercase keys instead of `DOCS_INE_FRENTE`.
- `docs_per_plan` entries that reference missing document catalog keys.
- `docs_per_plan` plan names that are not exact choices of `docs_plan_field`.
- Legacy Vision mappings that point at removed or misspelled `DOCS_*`.
- `docs_complete_for_plan` rules whose field does not match `docs_plan_field`.
- Prompt references to missing customer fields or missing KB documents.

### `core/atendia/tools/`

Tools used by the runner and prompts.

- `search_catalog.py`: catalog lookup.
- `lookup_requirements.py`: requirements lookup.
- `quote.py`: legacy quote tool surface.
- `vision.py`: document/image classification.
- `lookup_faq.py`: FAQ lookup.
- `rag/*`: retrieval and RAG helpers.
- `book_appointment.py`, `escalate.py`, `followup.py`: operational tools.

### `core/atendia/db/`

Database models and migrations.

Important models:

- `tenant.py`, `tenant_config.py`: tenant and tenant-level config.
- `customer.py`, `customer_fields.py`, `customer_note.py`: customer data.
- `conversation.py`, `message.py`, `message_attachment.py`: chat history and media.
- `turn_trace.py`: per-turn debug data.
- `knowledge_document.py`: KB documents/chunks.
- `agent.py`: agent configuration.
- `workflow.py`: workflows.
- `outbound_outbox.py`: outbound queue durability.

## Frontend Map

### App Shell

- `frontend/src/main.tsx`: React entry.
- `frontend/src/routes/__root.tsx`: root route.
- `frontend/src/routes/(auth)/route.tsx`: authenticated layout.
- `frontend/src/components/AppShell.tsx`: shell/sidebar/header.
- `frontend/src/features/navigation/`: menu and badges.

### Conversations

- `frontend/src/features/conversations/components/ConversationsPage.tsx`
- `ConversationDetail.tsx`
- `ChatWindow.tsx`
- `MessageBubble.tsx`
- `SystemEventBubble.tsx`
- `ContactPanel.tsx`: Datos de cliente, stage, documents, multimedia, risks and notes.
- `EditableDetailRow.tsx`: inline editable field row.
- Hooks: `useConversations`, `useConversationStream`, `useTenantStream`,
  `useCustomerAttrs`, `useContactPanel`.

Current important behavior:

- Datos de cliente shows tenant-defined `customer_field_definitions`.
- Canonical commercial fields use the same values the agent writes, for example
  `Nómina Tarjeta` and `10%`.
- `DOCS_*` fields display the actual document status from `customer.attrs`.
- Editing a `DOCS_*` field writes back to the structured customer attrs shape.

### Expediente / Documents

- `frontend/src/features/expediente/`: document catalog and docs-per-plan UI.
- `frontend/src/routes/(auth)/expediente.tsx`: route.
- `frontend/src/features/pipeline/components/PipelineEditor.tsx`: also exposes document config.

The document configuration path is tenant-editable and should not be copied into
Python as business constants.

### Pipeline

- `frontend/src/features/pipeline/components/PipelineKanbanPage.tsx`
- `PipelineEditor.tsx`
- `RuleBuilder.tsx`
- `PipelineVersionHistoryDrawer.tsx`

### Config

- `frontend/src/features/config/components/CustomerFieldsEditor.tsx`
- `IntegrationsTab.tsx`
- `QosConfigEditor.tsx`
- `FollowupsConfigEditor.tsx`
- `BrandFactsEditor.tsx`
- `ToneEditor.tsx`

### Agents

- `frontend/src/features/agents/components/AgentsPage.tsx`
- `ComposerModesEditor.tsx`
- `AgentWorkflowRefs.tsx`

### Knowledge

- `frontend/src/features/knowledge/components/KnowledgeBasePage.tsx`
- `frontend/src/features/knowledge/api.ts`

### Workflows And Observability

- `frontend/src/features/workflows/`
- `frontend/src/features/turn-traces/`
- `frontend/src/features/audit-log/`

## Tenant Configuration Surfaces

### Customer Fields

Table: `customer_field_definitions`

These fields drive:

- What appears in Datos de cliente.
- What NLU can extract.
- What the operator can edit.
- What pipeline rules can read.

Common keys for the financing flow:

- `antiguedad`
- `tipo_credito`
- `credito_plan`
- `modelo_moto`
- `DOCS_INE_FRENTE`
- `DOCS_INE_ATRAS`
- `DOCS_DOMICILIO`
- Additional tenant-specific `DOCS_*`

`field_options` can include:

```json
{
  "choices": ["10%", "15%", "20%", "30%"],
  "instructions": "Store only the exact percentage.",
  "is_document_status": true
}
```

### Pipeline Definition

Table: `tenant_pipelines.definition`

Important keys:

- `stages`
- `flow_mode_rules`
- `documents_catalog`
- `docs_per_plan`
- `docs_plan_field`
- `vision_doc_mapping` (legacy; kept for compatibility, not edited from the
  Expediente or Pipeline UI)

For docs completion, prefer:

```json
{
  "field": "tipo_credito",
  "operator": "docs_complete_for_plan"
}
```

and set:

```json
{
  "docs_plan_field": "tipo_credito"
}
```

### Documents

Canonical customer attrs shape:

```json
{
  "DOCS_DOMICILIO": {
    "status": "ok",
    "source": "vision",
    "confidence": 0.9
  }
}
```

Document requirements are configured from `documents_catalog`, `docs_per_plan`
and document-type customer fields. The old `vision_doc_mapping` field is kept in
the pipeline schema for compatibility with older tenants, but current operator
interfaces no longer ask operators to maintain a separate Vision matrix. New
document behavior should be modeled from Datos de cliente document fields and
expediente rules, not from a parallel Vision category table.

Legacy example only:

```json
{
  "ine": ["DOCS_INE_FRENTE", "DOCS_INE_ATRAS"]
}
```

### Quotes

Pricing output must be deterministic:

- Catalog evidence is retrieved.
- The runner extracts structured quote fields from catalog chunks.
- The final quote message is rendered from those structured fields.
- The LLM should not invent price, down payment, payment amount or term.

Relevant tests:

- `core/tests/runner/test_structured_quotes.py`
- `core/tests/state_machine/test_pipeline_evaluator.py`

## Recommended Extension Pattern

When adding behavior for a new vertical:

1. Add customer fields in `customer_field_definitions`.
2. Add Knowledge Base documents for catalog, requirements and policies.
3. Configure agent mode prompts.
4. Configure pipeline stages and rules.
5. Configure document catalog and docs-per-plan.
6. Run tests and a sandbox conversation.

Only add Python code when a generic capability is missing.

## Tests

Backend:

- `core/tests/api/*`
- `core/tests/runner/*`
- `core/tests/state_machine/*`
- `core/tests/webhooks/*`
- `core/tests/queue/*`
- `core/tests/workflows/*`

Frontend:

- `frontend/tests/features/*`
- `frontend/tests/e2e/*`
- `frontend/tests/lib/*`

Useful focused checks:

```powershell
cd core
uv run pytest tests/state_machine/test_pipeline_evaluator.py tests/runner/test_structured_quotes.py

cd ..\frontend
npm run typecheck
```
