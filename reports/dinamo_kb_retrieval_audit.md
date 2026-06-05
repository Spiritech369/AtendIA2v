# Dinamo KB And Retrieval Audit

Generated: 2026-06-03

Scope: audit catalog, requirements, FAQ and retrieval boundaries. No KB data or ingestion behavior was changed.

Final decision: KB_IS_USABLE_BUT_ROUTING_CONTRACT_IS_REQUIRED

## Source Inventory

| Source | File/Module | Purpose | Status |
| --- | --- | --- | --- |
| Catalog JSON | `docs/CatalogoMotos2026_DINAMO.json` | Model aliases, prices, cash price, financing plans, down payments, payments, specs | EXISTS |
| Requirements JSON | `docs/Requisitos_Credito_Dinamo.json` | Credit plan document requirements and rule that requirements come from file, not prompt | EXISTS |
| FAQ JSON | `docs/FAQ_DINAMO.json` | FAQ answers and objections | EXISTS_WITH_OVERLAP |
| Text KB files | `docs/ATENDIA_DINAMO_*_KB_IA.txt` | Retrieval-ready source text for catalog, FAQ and requirements | EXISTS |
| Knowledge OS | `core/atendia/knowledge/os/` | Tenant-scoped ingestion, retrieval, citations and parsers | EXISTS |
| Dinamo helper | `core/atendia/dinamo_atendia_kb.py` | Dinamo-specific helper for catalog, plan, quote, FAQ | EXISTS_BUT_TENANT_SPECIFIC |

## Retrieval Components

| Resolver | Files | Finding |
| --- | --- | --- |
| Catalog search | `core/atendia/tools/search_catalog.py`, `core/atendia/tools/deterministic.py` | Uses tenant-scoped published commercial catalog first, then legacy catalog data. Good base. |
| Quote | `core/atendia/tools/quote.py` | Returns structured quote data. Needs one canonical contract name/result shape. |
| Requirements | `core/atendia/tools/lookup_requirements.py` | Uses pipeline selection/document requirements. Stronger than prompt or FAQ. |
| FAQ | `core/atendia/tools/lookup_faq.py` | Useful for objections/general questions. Needs strict routing so it does not answer quote/requirements. |
| Document checklist | `core/atendia/contact_memory/document_checklist.py` | Plan-scoped checklist and completion logic. Strong target component. |

## Required Routing Rules

| User Need | Mandatory Tool | Must Not Use |
| --- | --- | --- |
| "Que modelos tienes?", "moto X", "la primera", "la del anuncio" | `catalog.retrieve` | Prompt memory or FAQ |
| "Cuanto queda?", "cotizame", "a credito", "de contado" | `quote.resolve` after canonical catalog result and plan/cash mode | Prompt math |
| "Que plan me toca?", "por fuera", "nomina", "recibos", "pensionado" | `credit_plan.resolve` | Prompt mapping |
| "Que documentos necesito?" | `requirements.retrieve` using resolved plan | FAQ generic requirements |
| "Ya mande mi INE" / attachment received | `document.check` and checklist reconciliation | Text claim alone |
| Buró, horarios, sucursal, objection, generic policy question | `faq.retrieve` | Quote or requirements resolvers unless the question asks those facts |

## Required Validation Matrix

| Validation Required By Brief | Current Evidence | Status | Risk / Note |
| --- | --- | --- | --- |
| Catalog is used for model, alias, price, plans and ficha tecnica | `docs/CatalogoMotos2026_DINAMO.json`, `search_catalog.py`, `deterministic.list_catalog`, commercial catalog service | PARTIAL | Present, but target requires one mandatory `catalog.retrieve` result for all paths |
| Requirements are used for plan, tipo_credito and documents | `docs/Requisitos_Credito_Dinamo.json`, `lookup_requirements.py`, pipeline document requirements | EXISTS | Good base; must outrank FAQ/prompt |
| FAQ is used for frequent questions | `docs/FAQ_DINAMO.json`, `lookup_faq.py`, tenant FAQ retrieval | EXISTS_PARTIAL | FAQ overlaps with requirements and commercial rules |
| Price is not calculated in prompt | Quote tool and quote safety exist | PARTIAL | Prompt contains quote-format instructions and legacy paths can still compensate with prompt/bridge logic |
| Requirements from different plans are not mixed | `lookup_requirements.py` and checklist are plan-scoped | EXISTS_PARTIAL | Prompt/FAQ generic requirements remain a routing risk |
| Generic docs are not answered when plan exists | Requirements resolver supports plan-scoped missing docs | PARTIAL | Must be enforced by routing contract so FAQ cannot answer first |
| Ambiguous model shows maximum 3 options | Dinamo prompt and runner candidate logic reference max candidate behavior | PARTIAL | Should become first-class `catalog.retrieve.requires_clarification` output |

## Gaps

1. Tool naming and result contracts are not fully unified. Examples: `quote` exists, but v2 safety expects `quote.resolve` semantics; catalog has `search_catalog` and `listCatalog`.
2. The FAQ source can overlap with requirements and down payment facts. Without routing, FAQ can produce generic docs or stale plan facts.
3. Dinamo-specific helper code is useful but should not become the target abstraction.
4. Knowledge OS exists, but the v2 runtime documentation still describes knowledge snippets as incomplete in some paths.
5. Catalog ambiguity handling exists in runner logic, but the target should make ambiguity a first-class tool result.
6. Quote safety is strong in v2 but depends on canonical tool evidence being present in every live path.

## Target Tool Result Evidence

Every retrieval result should include:

- `tenant_id`
- `source_id` or `collection_id`
- `record_id`
- `canonical_label`
- `confidence`
- `citations` or source references
- `staleness/version` where applicable
- `requires_clarification` when ambiguous
- `safe_to_persist_fields` for StateWriter

## Audit Conclusion

The KB data is usable and mostly well separated by topic. The remaining risk is routing authority: catalog, quote, plan and requirements must be mandatory deterministic tools, and FAQ must be prevented from answering facts owned by those tools.
