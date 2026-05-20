# AtendIA v2 - Frontend Interface Map

Last manual update: 2026-05-20.

This file is the quick map for frontend interface changes. Use it when the task
is visual, layout, navigation, forms, operator workflow, or a page-specific UI
change.

## App Shell And Routing

- `frontend/src/main.tsx`: React entrypoint.
- `frontend/src/routes/__root.tsx`: root route and global providers.
- `frontend/src/routes/(auth)/route.tsx`: authenticated app layout.
- `frontend/src/components/AppShell.tsx`: sidebar/header shell.
- `frontend/src/features/navigation/menu-config.ts`: sidebar menu entries.
- `frontend/src/features/navigation/hooks.ts`: navigation badge data.

## Customer And Conversation UI

- `frontend/src/features/conversations/components/ConversationsPage.tsx`: inbox page.
- `frontend/src/features/conversations/components/ConversationDetail.tsx`: selected conversation layout.
- `frontend/src/features/conversations/components/ChatWindow.tsx`: message list and composer area.
- `frontend/src/features/conversations/components/MessageBubble.tsx`: individual chat bubbles.
- `frontend/src/features/conversations/components/SystemEventBubble.tsx`: system events in chat.
- `frontend/src/features/conversations/components/ContactPanel.tsx`: Datos del cliente, document status, stage, notes and media.
- `frontend/src/features/conversations/components/EditableDetailRow.tsx`: inline editable customer fields.
- `frontend/src/features/conversations/components/FieldSuggestionsPanel.tsx`: AI field suggestions.

## Customer Data Configuration

- `frontend/src/features/config/components/CustomerFieldsEditor.tsx`: Datos cliente field definitions, including document-type fields and document review instructions.
- `frontend/src/features/config/components/RunnerRulesEditor.tsx`: runtime behavior rules.
- `frontend/src/features/config/components/NLUConfigEditor.tsx`: NLU/provider configuration.
- `frontend/src/features/config/components/IntegrationsTab.tsx`: channel/integration configuration.

## Expediente And Documents

- `frontend/src/features/expediente/components/ExpedientePage.tsx`: document catalog and docs-per-case rules.
- `frontend/src/routes/(auth)/expediente.tsx`: Expediente route.

Expediente no longer exposes a separate Vision mapping matrix. Document identity
and review expectations should come from Datos cliente document fields; required
documents per case live in Expediente.

## Pipeline UI

- `frontend/src/features/pipeline/components/PipelineKanbanPage.tsx`: stage board.
- `frontend/src/features/pipeline/components/PipelineEditor.tsx`: stage/rule/prompt configuration. The legacy Vision auto-mapping block is not shown here and saves clear `vision_doc_mapping`.
- `frontend/src/features/pipeline/components/RuleBuilder.tsx`: generic condition builder.
- `frontend/src/features/pipeline/components/StageDependencyView.tsx`: stage dependency display.
- `frontend/src/features/pipeline/components/PipelineVersionHistoryDrawer.tsx`: pipeline versions.

## Agents, Knowledge And Workflows

- `frontend/src/features/agents/components/AgentsPage.tsx`: agent list and editor surface.
- `frontend/src/features/agents/components/ComposerModesEditor.tsx`: mode prompt UI.
- `frontend/src/features/knowledge/components/KnowledgeBasePage.tsx`: KB management.
- `frontend/src/features/workflows/components/WorkflowsPage.tsx`: workflow list.
- `frontend/src/features/workflows/components/WorkflowEditor.tsx`: workflow builder.
- `frontend/src/features/workflows/components/WorkflowCanvas.tsx`: visual workflow canvas.

## Debug And Admin Surfaces

- `frontend/src/features/turn-traces/components/TurnTraceInspector.tsx`: trace inspector.
- `frontend/src/features/turn-traces/components/TurnPanels.tsx`: trace panels.
- `frontend/src/features/turn-traces/components/TurnStoryView.tsx`: readable turn story.
- `frontend/src/features/config-linter/components/ConfigLinterPage.tsx`: configuration warnings.
- `frontend/src/features/audit-log/AuditLogPage.tsx`: audit log.

## Shared UI

- `frontend/src/components/ui/*`: shadcn-style primitives.
- `frontend/src/components/sidebar/*`: sidebar primitives.
- `frontend/src/lib/utils.ts`: shared UI utility helpers.
