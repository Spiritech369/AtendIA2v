# Propuesta de configuracion tenant/domain para Dinamo

Fecha: 2026-06-03
Estado: propuesta documental. No se aplico a base de datos, no se activo trafico, no se habilitaron acciones ni workflows reales.

## Decision

Dinamo debe modelarse como tenant del dominio `vehicle_credit_sales`, no como caso especial dentro de `agent_runtime_v2`.

La configuracion propuesta traduce la operacion de Dinamo a contratos universales: campos, catalogo, planes, cotizacion, requisitos, documentos, pipeline, eventos, guardas, workflows y frontend.

## Identidad propuesta

| Campo | Valor propuesto |
| --- | --- |
| `tenant_slug` | `dinamo_motos_nl` |
| `domain` | `vehicle_credit_sales` |
| `locale` | `es-MX` |
| `timezone` | `America/Mexico_City` |
| `agent_role` | Asesor comercial de motos con credito |
| `runtime_mode` | `v2_shadow_until_evaluated` |
| `live_send_enabled` | `false` |
| `actions_enabled` | `false` |
| `workflow_side_effects_enabled` | `false` |

## Entidades

| Entidad universal | Dinamo |
| --- | --- |
| `product` | Moto o modelo seleccionado |
| `plan` | Plan de credito |
| `quote` | Cotizacion vigente por producto y plan |
| `requirements` | Requisitos/documentos por plan |
| `eligibility` | Reglas declarativas de elegibilidad |
| `customer_profile` | Datos operativos del contacto |

## Campos canonicos propuestos

| Key universal | Label Dinamo | Tipo | Owner | Escritura | Evidencia |
| --- | --- | --- | --- | --- | --- |
| `product_selection` | Moto seleccionada | string | model/tool | auto si coincide catalogo | catalog o mensaje cliente |
| `product_catalog_id` | ID de catalogo | string | tool | tool_only | catalog.search |
| `plan_selection` | Plan de credito | enum | model/tool | auto si coincide plan valido | plan resolver o mensaje cliente |
| `down_payment_amount` | Enganche | money | model/tool | suggest_review | mensaje cliente o quote |
| `payment_amount` | Pago | money | tool | tool_only | quote.resolve |
| `payment_frequency` | Frecuencia | enum | tool | tool_only | quote.resolve |
| `quote_snapshot_id` | Cotizacion validada | string | tool | tool_only | quote.resolve |
| `quote_valid_until` | Vigencia | date | tool | tool_only | quote.resolve |
| `employment_seniority` | Antiguedad laboral | string | model | auto si explicita | mensaje cliente |
| `income_amount` | Ingreso | money | model | suggest_review | mensaje cliente |
| `bureau_mentioned` | Buro mencionado | boolean | model | auto si explicito | mensaje cliente |
| `bureau_status` | Estado buro | enum | human/tool | suggest_review | evidencia revisada |
| `id_document_status` | INE | document_status | tool/human | attachment_required | adjunto o revision |
| `proof_of_address_status` | Comprobante domicilio | document_status | tool/human | attachment_required | adjunto o revision |
| `proof_of_income_status` | Comprobante ingresos | document_status | tool/human | attachment_required | adjunto o revision |
| `requirements_complete` | Papeleria completa | boolean | system | system_derived | requirements.lookup + adjuntos |
| `human_handoff_needed` | Requiere humano | boolean | system/model | auto con razon | guard/handoff |

## Pipeline propuesto

| Stage key | Label | Rol universal | Entrada |
| --- | --- | --- | --- |
| `nuevo` | Nuevo | `new` | Lead creado o primera conversacion. |
| `primer_contacto` | Primer contacto | `qualified` | Cliente respondio o intencion identificada. |
| `moto_identificada` | Moto identificada | `selection` | `product_selection` validado o sugerido con confianza alta. |
| `plan_identificado` | Plan identificado | `selection` | `plan_selection` validado. |
| `cotizado` | Cotizado | `quoted` | `quote_snapshot_id` creado por `quote.resolve`. |
| `papeleria_solicitada` | Papeleria solicitada | `requirements` | `requirements_requested` emitido con requisitos de tool. |
| `papeleria_recibida` | Papeleria recibida | `requirements` | Al menos un documento recibido con adjunto/evidencia. |
| `papeleria_completa` | Papeleria completa | `requirements` | `requirements_complete=true` derivado por sistema. |
| `en_revision_humana` | En revision humana | `handoff` | Reglas sensibles, duda, inconsistencia o guard block. |
| `cerrado_ganado` | Cerrado ganado | `closed_won` | Confirmacion humana. |
| `cerrado_perdido` | Cerrado perdido | `closed_lost` | Confirmacion humana o cliente no interesado. |

## Eventos de negocio

| Evento universal | Uso Dinamo |
| --- | --- |
| `lead_started` | Primer turno operativo. Idempotente por contacto/conversacion. |
| `selection_identified` | Moto seleccionada. |
| `plan_identified` | Plan elegido o inferido con evidencia. |
| `offer_quoted` | Cotizacion valida generada por herramienta. |
| `requirements_requested` | Se piden documentos/requisitos correctos del plan. |
| `requirements_partial` | Se recibe algun documento validable. |
| `requirements_complete` | Requisitos completos por sistema. |
| `human_handoff_requested` | Requiere asesor humano. |
| `policy_blocked` | Se bloqueo una respuesta, escritura o accion. |

## Herramientas obligatorias

| Tema | Herramienta | Obligatoria cuando |
| --- | --- | --- |
| Catalogo | `catalog.search` | Se menciona moto/modelo, disponibilidad, precio de lista o seleccion. |
| Planes | `credit_plan.resolve` | Se menciona plan, enganche, mensualidad o modalidad de credito. |
| Cotizacion | `quote.resolve` | Se va a mostrar precio, pago, enganche, vigencia o cotizacion. |
| Requisitos | `requirements.lookup` | Se piden documentos, papeleria o requisitos. |
| FAQ/politicas | `faq.lookup` | Se responde sobre buro, aprobacion, restricciones o politica comercial. |
| Documentos | `document.check` | Se intenta marcar documento recibido, aprobado o rechazado. |

## Guardas Dinamo

| Guardia | Regla |
| --- | --- |
| `quote_snapshot_guard` | No mostrar pagos/precios sin snapshot vigente de `quote.resolve`. |
| `no_cash_quote_for_credit_guard` | Si el contexto es credito, no mezclar precio contado como cotizacion de credito. |
| `requirements_plan_guard` | No pedir papeleria sin resolver plan/requisitos. |
| `document_real_guard` | Texto del cliente no cuenta como documento recibido. Requiere adjunto o revision. |
| `doc_complete_guard` | `requirements_complete` solo es system-derived. |
| `no_approval_guard` | No prometer aprobacion de credito. |
| `bureau_no_auto_reject_guard` | Mencionar buro no implica rechazo automatico. |

## Frontend Dinamo desde metadata

El frontend debe mostrar:

- Card de seleccion: moto, plan, cotizacion y vigencia.
- Card de requisitos: documentos faltantes, recibidos, rechazados y source.
- Card de elegibilidad: antiguedad laboral, ingreso, buro mencionado, estado buro.
- Timeline de eventos: lead, moto, plan, cotizacion, papeleria, handoff.
- Trace por turno: GPT propuso, herramientas ejecutadas, AtendIA valido, guardas.
- Badges de valor: `proposed`, `validated`, `needs_review`, `rejected`.

## No aplicar todavia

Esta propuesta no debe instalarse ni activarse hasta que existan:

1. `tenant_domain_contract` validado.
2. `mandatory_tool_contract` conectado.
3. Fixtures de simulacion Dinamo.
4. Tests de state writer, tools, guards, workflow idempotency y frontend rendering.
5. Comparacion shadow contra runner legacy.
