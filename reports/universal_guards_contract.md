# Contrato universal de guards

Fecha: 2026-06-03
Objetivo: separar validacion deterministica de prompts y hacer que las reglas sensibles sean tenant/domain scoped.

## Principio

Un guard no escribe copy visible. Un guard acepta, advierte, bloquea o reescribe datos estructurados antes de que lleguen a memoria, pipeline, workflows o `TurnOutput.final_message`.

## Resultado estandar

```json
{
  "guard_id": "quote_snapshot_guard",
  "scope": "final_message",
  "result": "blocked",
  "reason": "final message mentions a payment amount without a trusted quote snapshot",
  "affected_items": [],
  "evidence_refs": [],
  "suggested_next_step": "run quote.resolve"
}
```

## Guards universales

| Guard | Scope | Regla | Bloquea |
| --- | --- | --- | --- |
| `tenant_isolation_guard` | tool/state/trace | Todo dato debe pertenecer al tenant actual. | Si |
| `mandatory_tool_guard` | tool/final/state | Facts sensibles requieren tool obligatoria. | Si |
| `no_invented_fact_guard` | final/state | No permite facts sin evidence. | Si |
| `state_write_guard` | state | Valida write policy, source, confidence y evidence. | Si |
| `lifecycle_transition_guard` | lifecycle | Valida etapa, transicion y regla. | Si |
| `workflow_idempotency_guard` | workflow | Evita side effects duplicados y loops. | Si |
| `attachment_evidence_guard` | state/document | Documento recibido/completo requiere adjunto o revision humana. | Si |
| `final_copy_guard` | final_message | Revisa copy visible contra facts validados. | Si |
| `provider_fallback_guard` | provider/final | Controla fallback, parse repair y circuito. | A veces |
| `human_handoff_guard` | lifecycle/action | Escala casos sensibles o inciertos. | No siempre |
| `repetition_progress_guard` | final_message | Evita repetir sin avanzar. | Puede reescribir |

## Dinamo como configuracion de guards

Estos guards son especificos de la configuracion Dinamo, pero implementan patrones universales.

| Guard Dinamo | Patron universal | Regla |
| --- | --- | --- |
| `quote_snapshot_guard` | oferta/cotizacion confiable | No mostrar pagos, enganche o vigencia sin `quote.resolve`. |
| `no_cash_quote_for_credit_guard` | compatibilidad de oferta | No presentar precio contado como mensualidad/plan de credito. |
| `requirements_plan_guard` | requisitos por seleccion | No pedir papeleria sin plan o requisitos resueltos. |
| `document_real_guard` | evidencia de adjunto | "Ya lo mande" no marca documento recibido sin adjunto/revision. |
| `doc_complete_guard` | completitud derivada | Papeleria completa solo se deriva por sistema. |
| `no_approval_guard` | promesa sensible | No prometer aprobacion de credito. |
| `bureau_no_auto_reject_guard` | politica sensible | Mencionar buro no implica rechazo automatico. |

## Enforce points

| Momento | Guards |
| --- | --- |
| Antes de tools | `tenant_isolation_guard`, `mandatory_tool_guard` |
| Despues de tools | `no_invented_fact_guard`, `state_write_guard` |
| Antes de lifecycle | `lifecycle_transition_guard` |
| Antes de workflows | `workflow_idempotency_guard`, `tenant_isolation_guard` |
| Antes de final message | `final_copy_guard`, `quote_snapshot_guard`, `repetition_progress_guard` |
| Ante falla provider | `provider_fallback_guard`, `human_handoff_guard` |

## Inputs minimos

Un guard debe recibir:

- Tenant/domain contract version.
- Turn id y tenant id.
- GPT proposed output.
- Tool requirements y results.
- Current state.
- Proposed state/lifecycle/actions.
- Draft/final message candidate.
- Evidence refs.

## Outputs minimos

Un guard debe devolver:

- `result`.
- `reason`.
- `affected_items`.
- `evidence_refs`.
- `blocking`.
- `rewrite`, si aplica.
- `workflow_event`, si genera `policy_blocked` o handoff.

## Invariantes

1. Los guards no deben depender de palabras hardcodeadas en core para una vertical.
2. Las reglas especificas se declaran en tenant/domain contract.
3. Todo block debe aparecer en trace y frontend.
4. Todo rewrite de final copy debe conservar `TurnOutput.final_message` como autoridad.
5. Los guards no deben ejecutar acciones externas.

## Tests recomendados

- Tenant isolation bloquea catalogo de otro tenant.
- Mandatory tool bloquea precio sin quote tool.
- State write bloquea `requirements_complete` propuesto por modelo.
- Attachment guard bloquea documento sin adjunto.
- Workflow idempotency evita doble evento `offer_quoted`.
- Bureau guard marca handoff/review, no rechazo automatico.
