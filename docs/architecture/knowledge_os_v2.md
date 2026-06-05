# Knowledge OS v2

## Purpose

Knowledge OS v2 is the evidence layer for the Agent-First runtime. It gives the
agent structured snippets and citations, but it does not write final customer
copy and it does not replace the legacy KB routes yet.

The rule stays:

`AgentRuntime` converses. `Knowledge` informs. `Actions` execute. `Lifecycle`
measures. `Workflows` automate. `Policy` validates.

## Relationship With Legacy KB

Existing KB surfaces remain intact:

- `/api/v1/knowledge`
- `tenant_faqs`
- `tenant_catalogs`
- `knowledge_documents`
- `knowledge_chunks`
- `core/atendia/tools/rag`

Knowledge OS v2 adds a normalized layer around:

- `KnowledgeSource`
- `KnowledgeItem`
- `KnowledgeChunk`
- `KnowledgeCitation`
- `KnowledgeRetrievalLog`

The legacy tables are now adapted read-through into this shape. Knowledge OS v2
can retrieve from native v2 sources first, then from legacy FAQ, catalog, and
document chunks without copying legacy content or changing `/api/v1/knowledge`.

## Models

- `knowledge_sources`: tenant-scoped source metadata. Supports `file`, `url`,
  `faq`, `table`, and `manual`; content types such as `faq`, `policy`,
  `pricing`, `catalog`, `services`, `appointment_rules`, `document_rules`, and
  `general`; lifecycle statuses from `draft` to `expired`.
- `knowledge_items`: normalized content units inside a source.
- `knowledge_os_chunks`: retrieval units with optional embeddings.
- `knowledge_retrieval_logs`: audit trail for query, selected chunks and
  citations.

The DB model for v2 chunks is named `KnowledgeOSChunk` to avoid colliding with
the legacy `KnowledgeChunk` model/table.

## Ingestion

Implemented in `core/atendia/knowledge/os/ingestion.py`:

- manual/plain text;
- FAQ records;
- TXT/MD file bytes;
- PDF text extraction with page metadata;
- DOCX paragraphs, headings, and tables;
- CSV/TSV rows with structured data;
- XLSX sheets/rows with structured data;
- images as metadata-only sources.

URL ingestion, OCR/vision extraction for images, and crawler freshness remain
pending.

## Retrieval

Implemented in `core/atendia/knowledge/os/retrieval.py`.

The MVP uses deterministic textual scoring:

- filters by `tenant_id`;
- filters active sources/items/chunks;
- optionally filters by `allowed_agent_ids` in source metadata;
- adapts legacy `tenant_faqs`, `tenant_catalogs`, and
  `knowledge_documents/knowledge_chunks` into the same evidence shape;
- returns an `EvidencePack` with `answerable`, `confidence`, `snippets`,
  `citations`, `source_cards`, empty `conflicts`, and optional `missing_info`.

Hybrid/vector retrieval can plug into the same repository interface later. The
legacy RAG retriever remains unchanged.

## Citations

`citations.py` converts retrieved records into:

- source cards for UI/test chat;
- citations carrying source, item and chunk IDs;
- snippets suitable for `agent_runtime_v2`.

## AgentRuntime Integration

`ContextBuilder` now accepts an optional `knowledge_provider`. When present, it
calls `retrieve(...)` and maps Knowledge OS citations into
`TurnContext.knowledge_citations`. If retrieval fails or no provider exists,
context building continues with empty citations.

AgentRuntime v2 and Test Chat v2 use `UnifiedKnowledgeProvider` where they have
a database session, so native Knowledge OS sources and legacy-adapted sources are
available together. This does not change production legacy runner behavior.

## Blueprint Templates

`BlueprintService.create_draft_knowledge_templates_for_blueprint(...)` creates
empty draft `KnowledgeSource` rows for the blueprint's expected categories, such
as `pricing`, `catalog`, `services`, `appointment_rules`, `document_rules`, and
`policy`. These rows are idempotent and marked with
`metadata_json.template_kind=blueprint_knowledge`.

Draft templates do not count as uploaded knowledge. Onboarding readiness reports
whether the tenant has no source, empty draft templates, or at least one active
source.

## Tests

Focused tests:

```powershell
cd core
uv run pytest tests/knowledge_os tests/agent_runtime tests/test_config.py
```

DB shape tests for migration 058:

```powershell
cd core
uv run pytest tests/db/test_migration_058.py tests/db/test_kb_models.py
```

The DB tests require the local test database to be migrated through revision
`x0y1z2a3b4c5`.

## Pending

- vector/hybrid retrieval over `knowledge_os_chunks.embedding`;
- URL ingestion and crawler freshness;
- OCR/vision extraction for image documents;
- source replacement/archive operations;
- deeper conflict detection reuse from the legacy RAG module.
