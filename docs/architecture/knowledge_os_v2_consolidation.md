# Knowledge OS v2 Consolidation

## Status

Knowledge OS v2 is now the coherent evidence shape for AgentRuntime v2, Test Chat v2, onboarding readiness, and future eval surfaces.

Native Knowledge OS sources remain the preferred path. Legacy KB stays intact and is read through adapters:

- `tenant_faqs` -> `KnowledgeSource(type=faq, content_type=faq)`.
- `tenant_catalogs` -> `KnowledgeSource(type=table, content_type=catalog)`.
- `knowledge_documents/knowledge_chunks` -> `KnowledgeSource(type=file)` plus chunk metadata.
- legacy RAG chunks can be converted into `EvidencePack`, `KnowledgeCitation`, and source cards.

No legacy content is copied into v2 tables by the adapter.

## Retrieval

`UnifiedKnowledgeProvider` retrieves native `knowledge_sources/items/chunks` first, then legacy-adapted rows. It keeps tenant filtering mandatory and supports source-id filters used by Agent Studio and Test Chat.

Retrieval remains a textual MVP. Vector/hybrid retrieval, crawler ingestion, URL ingestion, and OCR are intentionally out of scope.

## Blueprint Templates

Blueprints can create idempotent draft `KnowledgeSource` templates through:

`BlueprintService.create_draft_knowledge_templates_for_blueprint(...)`

Templates are empty draft native sources tagged with:

- `template_kind=blueprint_knowledge`
- `template_empty=true`
- `blueprint_id`
- `blueprint_category`

Draft templates do not count as uploaded knowledge until real content is active.

## Onboarding

After selecting a blueprint, onboarding stores expected knowledge categories in the checklist and creates draft templates. Publish readiness distinguishes:

- `no_source`
- `draft_template_empty`
- `no_active_source`
- `active_source`

Legacy published FAQ/catalog/document content counts as active knowledge for migration compatibility.

## Agent Studio

Knowledge source options list native Knowledge OS sources first. Legacy rows still appear, marked with `badge=legacy`, `adapted=true`, and `legacy_table` metadata.

## Remaining Gaps

- Native vector/hybrid retrieval.
- URL/crawler ingestion and freshness jobs.
- OCR for images beyond metadata-only ingestion.
- Source replacement/archive operations.
- Full conflict detection parity with legacy RAG.
