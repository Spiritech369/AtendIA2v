# Knowledge Ingestion v2

Knowledge OS v2 now has file parsers that normalize business knowledge into the existing `KnowledgeSource`, `KnowledgeItem`, `KnowledgeChunk`, citation, and retrieval flow. The legacy KB/upload stack remains in place; this layer is an adapter for AgentRuntime v2 and test/eval surfaces.

## Supported Inputs

- `PDF`: extracts text per page with `page` metadata for citations.
- `DOCX`: extracts paragraph sections by heading and table rows.
- `TXT/MD`: decodes UTF-8 text into a single document section.
- `CSV/TSV`: detects dialect/header rows, preserves each row as `structured_data`, and creates row-level chunks.
- `XLSX`: reads sheets with `openpyxl`, detects headers, preserves rows as `structured_data`, and includes `sheet` metadata.
- Images (`jpg`, `png`, `webp`, `gif`, `tiff`, `bmp`): metadata-only stub. OCR/vision is not enabled in this task.

Not supported yet:

- URL ingestion.
- OCR/vision text extraction.
- Crawlers and freshness recrawls.

Parser outputs use `ParsedDocument`:

- `extracted_text`
- `sections`
- `tables`
- `metadata`
- `warnings`

## Statuses

`KnowledgeSource.status` supports:

- `processing`
- `active`
- `error`
- `partially_processed`

The synchronous MVP creates the source after parsing, so `processing` is available for async worker integration but is not persisted as an intermediate state yet. Parser warnings produce `partially_processed`; parse failures produce `error`.

## Tables

CSV/XLSX/DOCX tables are normalized as row items:

- `KnowledgeItem.structured_data` keeps the row dictionary.
- Row chunks keep original terms such as category, price, currency, and service/product names.
- Metadata includes `headers`, `row_index`, and `sheet` where applicable.

No vertical-specific columns are required. Generic title detection uses common label-like columns such as `title`, `name`, `product`, and `service`, but retrieval works from all row text.

## Citations

Citation metadata merges source, item, and chunk metadata, so answers can surface source cards and locations:

- PDF: `file_type=pdf`, `page`
- DOCX: `file_type=docx`, `section` or `table`
- CSV: `file_type=csv`, `row_index`
- XLSX: `file_type=xlsx`, `sheet`, `row_index`

`KnowledgeRetrievalService` includes `active` and `partially_processed` sources, while tenant filtering remains mandatory. Retrieval is still textual MVP scoring; vector/hybrid search is intentionally not enabled for Knowledge OS v2 yet.

## Retry And Reindex

There is no Knowledge OS v2 async indexing worker in this task. Reindex/retry should call `KnowledgeIngestionService.ingest_file(...)` again from an admin/upload route or future job, then replace or archive the old source once repository update/delete operations exist.

## Pending

- OCR/vision for image documents.
- URL crawling.
- Async ingestion worker with durable `processing` transitions.
- Duplicate detection and source replacement.
- Embedding/hybrid search once the vector path is wired to Knowledge OS v2.
