# Dinamo Contact Fields Audit

Generated: 2026-06-03

Scope: audit customer/contact fields, field authority, and StateWriter ownership. No fields or configuration were changed.

Final decision: STATE_WRITER_SHOULD_CONTROL_ALL_BUSINESS_FIELDS_AFTER_TOOL_CONTRACTS

## High-Level Finding

The target contact memory model is clear, but the current codebase still has mixed legacy and target field names. Runtime v2 has a strong StateWriter, while the live Dinamo/legacy path still uses bridge policies and uppercase/internal keys.

The required direction is to make StateWriter the only accepted writer for business fields, with tenant-configured aliases mapping old names into canonical fields.

## Field Authority Table

| Target Field | Legacy/Current Names Seen | Target Owner | Required Evidence | Status |
| --- | --- | --- | --- | --- |
| `Moto` | `MOTO`, `MODELO_INTERES`, `product`, `model`, `last_quote.product` | StateWriter after `catalog.retrieve` | Canonical catalog item or quote snapshot | PARTIAL |
| `Tipo_Compra` | `cash`, `credit`, `CREDITO`, quote mode flags | StateWriter after intent/tool evidence | Explicit user intent or quote mode | PARTIAL |
| `Cumple_Antiguedad` | `FILTRO`, `ANTIGUEDAD_LABORAL`, `CUMPLE_ANTIGUEDAD` | StateWriter | User answer evaluated against tenant threshold | PARTIAL |
| `Plan_Credito` | `CREDITO`, `PLAN`, `PLAN_CREDITO`, selection key | StateWriter after `credit_plan.resolve` | Canonical plan code/name | PARTIAL |
| `Plan_Enganche` | `ENGANCHE`, `PLAN_ENGANCHE` | StateWriter after `credit_plan.resolve` | Down payment percent or amount from plan/quote | PARTIAL |
| `Buro` | `BURO`, FAQ/objection metadata | StateWriter or noncritical note policy | Explicit user statement; no auto reject | NEEDS_CONTRACT |
| `Ubicacion_Interes` | location/sucursal fields | StateWriter | Explicit user location or selected branch | NEEDS_CONTRACT |
| `Cotizacion_Enviada` | `quote_sent`, `COTIZACION_ENVIADA` | QuoteSafetyGuard/StateWriter | Accepted visible quote from `quote.resolve` | STRONG_IN_V2 |
| `Ultima_Cotizacion` | `last_quote`, `quote_snapshot`, `ULTIMA_COTIZACION` | QuoteSafetyGuard/StateWriter | Trusted quote result only | STRONG_IN_V2 |
| `Docs_Checklist` | checklist JSON, document memory | Document checker + StateWriter | Plan-scoped checklist | EXISTS |
| `Doc_Incompletos` | missing docs, rejected docs | Document checker + StateWriter | Checklist result | EXISTS_PARTIAL |
| `Doc_Completos` | docs_complete, stage flags | Document checker + StateWriter + pipeline evaluator | All required docs accepted for selected plan | EXISTS_PARTIAL |
| `Ultimo_Documento_Recibido` | last attachment metadata | Document checker + StateWriter | Attachment/document evidence | EXISTS_PARTIAL |
| `Pipeline` | `current_stage`, lifecycle stage, pipeline status | Lifecycle service/workflow engine | Stage rule result | EXISTS_PARTIAL |
| `Handoff_Humano` | `needs_human`, handoff flags | Handoff policy/workflow engine | Structured risk/request/low-confidence evidence | EXISTS_PARTIAL |
| `Motivo_Handoff` | handoff reason | Handoff policy/workflow engine | Structured reason enum | EXISTS_PARTIAL |
| `Followup_Status` | followup scheduler state | Workflow/followup service | Deterministic schedule/action result | EXISTS_PARTIAL |

## Required Field Audit Matrix

| Field | Where Written Today | Who Writes / Proposes | Evidence Required | Can LLM Write Direct? | StateWriter Validation | Special Rule |
| --- | --- | --- | --- | --- | --- | --- |
| `Moto` | Legacy state policy, Dinamo bridge, v2 StateWriter | Advisor/bridge proposes; StateWriter should accept | Canonical catalog record or quote snapshot | No | Required target | Vague text like "moto del anuncio" must not persist |
| `Tipo_Compra` | Runner/quote policies/state proposals | Intent/policy proposes; StateWriter should accept | Explicit cash/credit intent or quote mode | No | Required target | Prevent credit intent receiving cash quote |
| `Cumple_Antiguedad` | Prompt-derived proposals, state policies, operational reconciler | Advisor/intent extractor proposes | User answer and tenant threshold | No | Required target | Do not repeat if already accepted |
| `Plan_Credito` | `resolve_credit_plan`, state proposals, pipeline selection | Tool should own | `credit_plan.resolve` result | No | Required target | No prompt plan constants |
| `Plan_Enganche` | `resolve_credit_plan`, quote result, state proposals | Tool should own | Plan/quote evidence | No | Required target | Changes invalidate quote |
| `Buro` | FAQ/intent metadata or field proposals | User statement should propose | Explicit user statement or FAQ category evidence | No | Needs contract | Never auto-reject only for Buro mention |
| `Ubicacion_Interes` | Contact fields/state proposals | User statement should propose | Explicit location/branch signal | No | Needs contract | Tenant/branch scoped |
| `Cotizacion_Enviada` | Quote safety/state policy/quote memory | QuoteSafetyGuard should own | Visible quote accepted from `quote.resolve` | No | Strong in v2 | Cannot be true if quote is blocked/stale |
| `Ultima_Cotizacion` | `last_quote`, quote snapshot, StateWriter | Quote tool should own | Trusted quote result/snapshot | No | Strong in v2 | Invalidate on moto/plan/mode change |
| `Docs_Checklist` | Document checklist/contact memory | `requirements.retrieve` + `document.check` | Plan-scoped checklist | No | Required target | One checklist per selected plan |
| `Doc_Incompletos` | Checklist/stage policy | Document checker should own | Missing/rejected checklist items | No | Required target | No text-only claim |
| `Doc_Completos` | Checklist/pipeline evaluator | Document checker + lifecycle should own | All required docs accepted | No | Required target | True only with real document evidence |
| `Ultimo_Documento_Recibido` | Attachment/vision/document memory | Attachment/document checker should own | Uploaded file/photo evidence | No | Required target | Papeleria Incompleta requires real attachment |
| `Pipeline` | Pipeline evaluator/lifecycle/legacy stage moves | Lifecycle/workflow should own | Stage rule or workflow event | No | Required target | No prompt-only stage move |
| `Handoff_Humano` | Handoff helper, needs_human flags, workflows | Handoff policy/workflow should own | Structured handoff reason | No | Required target | Avoid fallback-only false handoff |
| `Motivo_Handoff` | Handoff helper/workflow payload | Handoff policy should own | Reason enum and trace | No | Required target | Required for auditability |
| `Followup_Status` | Followup scheduler/workflow actions | Workflow/followup service should own | Scheduled action/event result | No | Required target | Idempotency required |

## Fields That Must Be StateWriter-Controlled

These fields should never be accepted directly from prompt text:

- `Moto`
- `Tipo_Compra`
- `Cumple_Antiguedad`
- `Plan_Credito`
- `Plan_Enganche`
- `Buro`
- `Ubicacion_Interes`
- `Cotizacion_Enviada`
- `Ultima_Cotizacion`
- `Docs_Checklist`
- `Doc_Incompletos`
- `Doc_Completos`
- `Ultimo_Documento_Recibido`
- `Pipeline`
- `Handoff_Humano`
- `Motivo_Handoff`
- `Followup_Status`

## StateWriter Rules Already Aligned With Target

1. Rejects customer-visible text inside tool/action results.
2. Blocks quote snapshot writes unless they come from trusted quote evidence.
3. Blocks `quote_sent` unless the quote guard has validated visible copy.
4. Invalidates quote snapshot and quote-sent status when product or plan changes.
5. Blocks document lifecycle/stage changes without attachment/checklist evidence.
6. Keeps state updates structured and auditable.

## Remaining Gaps

1. Legacy and target field names are mixed.
2. Some Dinamo bridge logic still proposes writes from heuristic plan/model/doc detection.
3. `credit_plan_invariants.py` contains global plan facts that should be tenant-scoped.
4. Quote snapshot authority is strong in v2 but not yet universal in the live path.
5. Handoff and workflow fields need event-based authority, not phrase-only authority.

## Recommended Contract

Every accepted field update should have:

- canonical field name
- old value
- new value
- source tool/action
- evidence id or citation
- confidence
- reason
- tenant id
- trace id
- invalidations caused by the write

## Audit Conclusion

StateWriter is the right target authority. The immediate blocker is not the StateWriter concept; it is that tool results and field names must be standardized so StateWriter can consistently decide what is safe to persist.
