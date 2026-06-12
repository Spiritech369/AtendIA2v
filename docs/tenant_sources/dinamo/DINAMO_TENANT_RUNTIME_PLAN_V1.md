# DINAMO — Plan de Configuración de Tenant V1 (runtime real)

**Fecha:** 2026-06-11
**Estado:** `PLAN_APPROVED_READY_TO_IMPLEMENT`
**Supersede/complementa:** `dinamo_runtime_blueprint_v1.json`, `dinamo_product_agent_mapping_v1.docx`
**Fuentes humanas:** `Requisitos_Dinamo-Junio2026.docx`, `Catalogo_Dinamo-Junio2026.docx`, `FAQ_Dinamo-Junio2026.docx`, `Flujo_Dinamo_Orden_y_Caos.docx`, `Prompt Agente IA.txt`

Este documento es el artefacto de planeación para configurar el tenant `dinamo` con contact fields reales, pipeline, workflows reales y agente IA, alineado a la ruta Respond-Style (LLM conversa / AtendIA orquesta-valida-audita). No es un plan de "bot de ifs": toda frase visible al cliente la redacta el LLM dentro del runtime validado, con la única excepción de plantillas de workflow editables que pasan por `customer_message.request` (vía única).

---

## 0. Decisiones cerradas en esta sesión (2026-06-11)

| # | Decisión | Valor cerrado |
|---|----------|---------------|
| D1 | Identidad del agente | **El agente ES Francisco Esparza.** No "asesor de apoyo", no "Frank". |
| D2 | Handoff | **Takeover invisible.** El humano (Francisco real) continúa la conversación con la misma identidad. El bot nunca dice "te paso con Francisco/Frank"; dice variantes de "déjame revisarlo bien y te confirmo por aquí". El cliente no percibe el cambio. |
| D3 | Alcance V1 | **Todo incluido:** follow-ups automáticos, revisión de documentos (vision), integraciones Google (Sheets/Drive/Form), transcripción de audio. |
| D4 | Follow-ups | 3 intentos: **3 h / 12 h / 3 días (72 h)** de silencio. Horario 7:00–23:00, jitter 2–10 min, cancelar si responde/handoff/terminal. (El 3er intento cambió de 36 h → 72 h respecto al blueprint.) |
| D5 | Contact fields seed actual | **Re-seed limpio.** Se archivan/eliminan los field definitions actuales de dinamo (plan_credito=plazos, docs_ine checkbox, etc.) y se crea el set canónico de la sección 2. |
| D6 | Tareas internas | **Sin entidad Task en V1.** `task.create` se materializa como `Notification` dirigida + `Conversation.assigned_user_id` + campo `Motivo_Handoff`. Entidad Task real queda para V2. |
| D7 | Contacto beta | **8128889241** → E.164 **+528128889241**. Gate de publicación amarrado a ese número exacto. |
| D8 | Candados | **Autorizado** y **CERRADO GANADO** bloqueados a humano/admin. La IA jamás los escribe. NO CALIFICA y CERRADO PERDIDO sí admiten automatización conservadora. |
| D9 | Google Cloud | **No existen credenciales.** El plan incluye fase de provisioning desde cero (proyecto GCP, service account, secrets por tenant). |
| D10 | Plazo de crédito | **Único: 72 quincenas en todos los planes** (FAQ_006). No existe concepto de plazo variable — los valores 12m/24m/36m/48m del seed viejo no existen en el negocio. No se crea campo de plazo. Si el cliente pide un plazo distinto → handoff (`excepcion_no_cubierta`); la IA no negocia plazos. |

Consecuencia de D1+D2 sobre los documentos fuente: todos los mensajes tipo "te paso con Francisco", "te paso con Frank", "ve con Francisco a la agencia" del Prompt, Flujo y blueprint **deben reescribirse** (ver sección 8). La dirección/ubicación de la agencia se mantiene, pero se ofrece como "ven a la agencia del centro, pregunta por mí".

---

## 1. Principio rector (no negociable)

- **El LLM conversa**: redacta el mensaje visible, maneja objeciones, pide datos faltantes, propone tool calls / field updates / workflow events / handoff.
- **AtendIA orquesta**: construye contexto, ejecuta tools fact-only, valida propuestas (RespondStyleTurnValidator), guarda campos vía StateWriter con evidencia, ejecuta workflows permitidos, decide send/no-send y audita.
- **Prohibido**: composers con ifs, plantillas de reparación, validators-guionistas, copy de workflow fuera de `customer_message.request`, blocked-phrase-lists como estrategia (las "frases prohibidas" del prompt son guía de comportamiento del LLM + claims del validator, no regex de reescritura).
- Los textos `respuesta_whatsapp` de los KB de Requisitos y las "respuestas sugeridas" del Flujo son **evidencia/ejemplos de tono para el LLM**, no plantillas que AtendIA inserta. El validator valida facts (montos, documentos, planes), no frases.

---

## 2. Contact Fields canónicos (re-seed limpio)

Modelo: `CustomerFieldDefinition` (`core/atendia/db/models/customer_fields.py`). Tipos disponibles hoy: `text`, `number`, `checkbox`, `select`, `multiselect`, `date`.

### 2.1 Campos de operación (visibles para Francisco en la UI)

| Label (visible) | key | Tipo | Opciones / formato | Escritura |
|---|---|---|---|---|
| Cumple Antigüedad | `Cumple_Antiguedad` | checkbox | true = ≥6 meses | IA con evidencia conversacional |
| Antigüedad Laboral | `Antiguedad_Laboral` | text | dato crudo: "3 años", "desde enero" | IA con evidencia |
| Plan Crédito | `Plan_Credito` | select | `Nómina Tarjeta`, `Nómina Recibos`, `Pensionados`, `Negocio SAT`, `Sin Comprobantes`, `Guardia de Seguridad` | IA con evidencia + validación contra KB requisitos |
| Plan Enganche | `Plan_Enganche` | select | `10%`, `15%`, `20%`, `30%` | **Solo derivado** del plan por regla fija (mapa 1→10, 2→15, 3→10, 4→15, 5→20, 6→30). La IA propone plan; el enganche lo escribe el workflow `state.write_contact_field` por derivación, nunca libre. |
| Moto | `Moto` | text | nombre canónico exacto del catálogo | IA, **solo si** `catalog.search`/`quote.resolve` confirmó el modelo (validator exige tool evidence). |
| Banco | `Banco` | text | nombre del banco | IA con evidencia |
| Periodicidad Pago | `Periodicidad_Pago` | select | `semanal`, `quincenal`, `catorcenal`, `mensual`, `desconocido` | IA con evidencia |
| Fecha Corte Estado | `Fecha_Corte_Estado` | text | fecha o texto de corte | IA/vision con evidencia documental |
| Docs Checklist | `Docs_Checklist` | text | JSON serializado `{doc_id: estado}` por plan | **Solo sistema** (document.check / expediente.evaluate) |
| Doc Incompletos | `Doc_Incompletos` | text | resumen legible de faltantes/inválidos | **Solo sistema** |
| Doc Completos | `Doc_Completos` | checkbox | true solo tras `expediente.evaluate` | **Solo sistema** |
| Cotización Enviada | `Cotizacion_Enviada` | checkbox | true si se envió cotización válida | **Solo sistema** (al confirmar send de un turno con quote citada) |
| Última Cotización | `Ultima_Cotizacion` | text | resumen: modelo, plan, enganche $, quincenal $, quincenas | **Solo sistema** (desde `quote.resolve` ejecutado) |
| Formulario | `Formulario` | select | `pendiente`, `enviado`, `completado_manual`, `completado_webhook` | sistema/humano |
| Asesor Asignado | `Asesor_Asignado` | text | default: Francisco (operador humano) | sistema/humano |
| Handoff Humano | `Handoff_Humano` | checkbox | activa takeover invisible | IA propone, workflow ejecuta |
| Motivo Handoff | `Motivo_Handoff` | select | `pago_reportado`, `humano_solicitado`, `expediente_completo`, `documento_dudoso`, `enojo_fuerte`, `excepcion_no_cubierta`, `conflicto_promesa_externa`, `fuera_de_nl`, `otro` | sistema (al activar handoff) |
| Pago Enganche Reportado | `Pago_Enganche_Reportado` | checkbox | reporte del cliente, NO pago validado | sistema (trigger handoff inmediato) |
| Vive o Trabaja NL | `Vive_o_Trabaja_NL` | select | `si`, `no`, `desconocido` | IA con evidencia |
| Transcripción Último Audio | `Transcripcion_Ultimo_Audio` | text | texto de la transcripción | **Solo sistema** (audio.transcribe) |
| Autorizado | `Autorizado` | checkbox | **CANDADO D8: solo humano/admin** | `AgentFieldPermission.can_write=false` para el agente |

### 2.2 Campos admin (auditoría/integraciones)

| key | Tipo | Escritura |
|---|---|---|
| `Solicitud_ID` | text | sistema |
| `Google_Sheets_Row_ID` | text | sistema (integración Sheets) |
| `Google_Drive_Folder_ID` | text | sistema (integración Drive) |
| `Google_Drive_File_IDs` | text (JSON serializado) | sistema |
| `Source_Version_ID` | text | sistema (versión de KB usada en el turno) |
| `Last_Runtime_Trace_ID` | text | sistema |
| `Followups_Enviados` | number | sistema (máx 3) |
| `Proximo_Followup` | date | sistema |

### 2.3 Permisos por agente (`AgentFieldPermission`)

- `can_write=true, evidence_required=true` para todos los campos "IA con evidencia".
- `can_write=false` para: `Autorizado`, `Docs_Checklist`, `Doc_Incompletos`, `Doc_Completos`, `Cotizacion_Enviada`, `Ultima_Cotizacion`, `Transcripcion_Ultimo_Audio`, todos los admin. El agente los **lee** (contexto) pero solo el sistema los escribe.
- `Plan_Enganche`: `can_write=false` para el agente; lo deriva el workflow al validar `Plan_Credito` (regla `sin_comprobantes_siempre_20`, `guardia_siempre_30`).

### 2.4 Gaps de plataforma detectados (mejoras pequeñas, no bloqueantes)

1. **Visibilidad por campo** (operación vs admin): hoy no existe; V1 lo resuelve con convención `field_options.visibility = "operator"|"admin"` en el JSONB y filtro en la UI de Datos de cliente. Item de implementación, bajo riesgo.
2. **Tipo `catalog_item`**: no existe; `Moto` queda `text` + validación dura en el validator (solo escribir si hay tool evidence de catálogo). No inventar un tipo nuevo en V1.
3. **Aliases de campos** (MODELO_INTERES, PLAN, ENGANCHE…): los documentos fuente y transcripts viejos usan alias. V1: tabla de alias en `field_options.aliases` (JSONB) consumida solo por el ContextPackageBuilder/StateWriter para resolución, jamás expuesta al cliente.

### 2.5 Re-seed (D5)

Script idempotente `core/scripts/seed_dinamo_v1.py` (nuevo) que:
1. Archiva los `CustomerFieldDefinition` actuales de dinamo (no DELETE físico: marcar deprecated en `field_options` o eliminar si no hay `CustomerFieldValue` reales — en dev no los hay). El `plan_credito` viejo con opciones 12m/24m/36m/48m se elimina sin migración de valores: esos plazos **nunca existieron en el negocio** (D10); el plazo es fijo de 72 quincenas y no requiere campo.
2. Crea el set 2.1 + 2.2 con `ordering` correcto.
3. Crea pipeline (sección 3), workflows (sección 4), bindings del agente (sección 6).
4. Registra `Source_Version_ID` de los KB ingestados.

---

## 3. Pipeline Dinamo V1 (`TenantPipeline.definition`)

Etapas activas (en orden) + terminales. Condiciones con el motor existente (`auto_enter_rules` + acción `move_stage` de workflows).

| id | label | Entra cuando (auto_enter_rules / workflow) | Sale cuando |
|---|---|---|---|
| `nuevos` | NUEVOS | default (conversación creada sin antigüedad) | `Cumple_Antiguedad` queda true/false |
| `plan` | PLAN | `Cumple_Antiguedad == true` | `Plan_Credito` + `Plan_Enganche` + `Moto` existen |
| `cliente_potencial` | CLIENTE POTENCIAL | los 3 campos del plan existen **y** `Cotizacion_Enviada == true` | cliente quiere avanzar o manda documento |
| `papeleria_incompleta` | PAPELERÍA INCOMPLETA | existe ≥1 documento recibido y `Doc_Completos == false` | `expediente.evaluate` confirma completo |
| `papeleria_completa` | PAPELERÍA COMPLETA | `Doc_Completos == true` | `Formulario` completado o revisión humana |
| `revision_humana` | REVISIÓN HUMANA / HANDOFF | `Handoff_Humano == true` (cualquier etapa, vía workflow `move_stage`, no auto_enter) | humano toma control / cierre |

Terminales (`is_terminal: true`):

| id | label | Automatización |
|---|---|---|
| `no_califica` | NO CALIFICA | auto conservador permitido (`Cumple_Antiguedad == false`) |
| `cerrado_perdido` | CERRADO PERDIDO | manual o auto conservador (follow-ups agotados + silencio prolongado — en beta: **solo manual**) |
| `cerrado_ganado` | CERRADO GANADO | **solo manual/admin (D8)** |

Notas de implementación:
- `auto_enter_rules` ya soporta `exists`/`equals`; las transiciones por evento (handoff, documento recibido) van por workflow `pipeline.transition` con acción `move_stage` para que queden auditadas como ejecución de workflow.
- `fallback: escalate_to_human` se conserva.
- El campo `docs_per_plan` del definition se llena desde el KB de requisitos (6 planes → lista de `doc_id`), no hardcodeado a 2 planes como el seed viejo.

---

## 4. Workflows reales V1

Mapeo blueprint → engine existente (`core/atendia/workflows/engine.py`). Triggers y acciones ya soportados salvo lo marcado **[NUEVO]**.

| Workflow | Trigger (engine) | Acciones (nodos) | Estado plataforma |
|---|---|---|---|
| `state.write_contact_field` | `field_extracted` (propuesta del LLM validada) | validación StateWriter → `update_field` → derivar `Plan_Enganche` si cambió `Plan_Credito` → log | ✅ existe; agregar nodo de derivación plan→enganche como `condition`+`update_field` |
| `pipeline.transition` | `field_updated`, `document_accepted`, `docs_complete_for_plan` | `condition` → `move_stage` → log | ✅ existe |
| `task.create` (D6: sin entidad) | `human_handoff_requested`, `webhook_received` | `notify_agent` (a Francisco) + `update_field(Motivo_Handoff)` | ✅ existe |
| `notification.create` | eventos críticos internos | `notify_agent` con dedupe por key | ✅ existe (dedupe: verificar/agregar clave de idempotencia) |
| `human.assign` | handoff o manual | `assign_agent` / set `assigned_user_id` + `update_field(Asesor_Asignado)` | ✅ existe |
| `handoff.start` | `human_handoff_requested` | `assign_agent` → `notify_agent` → `pause_bot` (modo limitado, ver 6.4) → `update_field(Handoff_Humano, Motivo_Handoff)` | ✅ existe |
| `customer_message.request` | workflow necesita mensaje visible | `template_message` con dedupe — **única vía de copy de workflow**, siempre a través de SendAdapter/outbox con send_scope canónico | ✅ existe (`template_message`); auditar que respete gate no-send |
| `followup.schedule` | silencio del cliente tras paso calificado | `followup` (FollowupScheduled) con horario 7–23, jitter 2–10 min, máx 3, cancelar al responder | ⚠️ parcial: `followup` existe; **[NUEVO]** quiet-hours + jitter + cancel-on-reply como config del nodo |
| `google_sheets.upsert_row` | `field_updated`, `stage_changed`, `document_accepted/rejected` | **[NUEVO]** acción `google_sheets_upsert` (o `http_request` a microservicio interno) | ❌ construir (Fase G) |
| `google_drive.upload_file` | archivo recibido (media inbound) | **[NUEVO]** acción `google_drive_upload`: carpeta `{telefono}_{nombre}_{fecha}`, subcarpetas `00_raw/01_aceptados/02_rechazados/03_formulario/99_notas_revision` | ❌ construir (Fase G) |
| `audio.transcribe` | audio inbound | **[NUEVO]** pipeline de transcripción → `update_field(Transcripcion_Ultimo_Audio)` → turno del agente usa la transcripción como input | ❌ construir (Fase H) |

Reglas duras:
- Ningún workflow escribe customer copy libre. Solo `customer_message.request` con plantillas registradas (sección 8) y dedupe.
- Workflows con side effects reales corren `execution_mode=dry_run_only` hasta el gate de beta (Publish Control), igual que la ruta Respond-Style: primero todo no-send/dry, luego se abre por kill switch.
- `Pago_Enganche_Reportado == true` → `handoff.start` inmediato con `Motivo_Handoff=pago_reportado`. La IA nunca valida pagos.

---

## 5. Knowledge Base (ingesta versionada)

Capa: `KnowledgeSource`/`KnowledgeOSChunk` + capa rápida `TenantCatalogItem`/`TenantFAQ` (ya existen, con ingest `ingest_dinamo_data.py`).

1. **Regenerar los 3 JSON aprobados** desde los DOCX de junio (los DOCX ya traen "bloques de recuperación" diseñados para esto):
   - `requisitos_dinamo_v2_1.json` — 6 planes, documentos por plan con `doc_id`, cantidades por periodicidad, mapa opción 1-6, reglas (`sin_comprobantes_siempre_20`, `guardia_siempre_30`, `no_mezclar_planes`, `no_prometer_aprobacion`).
   - `catalogo_dinamo_2026_05_17.json` — 34 modelos, 8 categorías, alias normalizados, ficha técnica, precios y planes 10/15/20/30 **pre-calculados** (regla dura: no calcular nada en runtime; `quote.resolve` devuelve el registro exacto). Plazo siempre 72 quincenas (D10): el número de quincenas viene del registro del catálogo, no se ofrece ni negocia otro plazo.
   - `faq_dinamo_v1.json` — 26 FAQs con detalle por plan, links validados (catálogo `https://wa.me/c/5218186016492`, maps, formulario).
2. **Versionado obligatorio** (prioridad de fuentes del blueprint): cada JSON con `source_id`, `source_type`, `version`, `hash`, `approved_by`, `approved_at`, `runtime_status`. El turno registra `Source_Version_ID`. Si DOCX y JSON contradicen, **manda el JSON aprobado**.
3. **Bindings del agente** (`AgentKnowledgeSourceBinding`): catálogo (required para cotizar), requisitos (required para requisitos), FAQ (prioridad menor). El validator ya exige: precio solo con `quote.resolve`, requisitos solo con `requirements.lookup` — los KB alimentan esas tools, no el prompt.
4. **Anti-invención**: el ContextPackageBuilder empaqueta snippets KB como facts citables con id de fuente; el LLM solo afirma lo que cita (claims con soporte, ya validado por RespondStyleTurnValidator).

---

## 6. Agente IA (Product Agent "Francisco Esparza — Dinamo")

### 6.1 Identidad y tono (D1)
- Nombre visible: **Francisco Esparza**, asesor de créditos de Dínamo Monterrey.
- es-MX, WhatsApp, informal-directo, sin emojis, máx 2 frases (hasta 4 si hay multi-pregunta), una sola pregunta de avance por turno, nunca expone variables/reglas/tools.

### 6.2 Estructura del prompt (AgentVersion.prompt_blocks)
Reusar el `Prompt Agente IA.txt` como base con estas **ediciones obligatorias**:
1. **Eliminar todo "te paso con Francisco/Frank"** (D2). Reemplazos de escalamiento (takeover invisible):
   - General: *"Déjame revisarlo bien y te confirmo por aquí en un momento."*
   - Pago reportado: *"Eso lo reviso directo antes de mover cualquier dato. Dame un momento y te confirmo por aquí."*
   - Dato sin fuente: *"Ese dato lo tengo que confirmar bien para no darte información incorrecta. Te lo confirmo por aquí."*
   - Visita presencial: *"Si prefieres, ven a la agencia del centro (Benito Juárez 801) y lo revisamos en persona."*
2. **Quitar los bloques que duplican lógica de motor** (mapeo fijo plan→enganche como instrucción de escritura, "guardar X=true"): el LLM **propone** field updates; la separación de responsabilidades queda como ya la describe la sección "Separación de responsabilidades" del prompt (que se conserva).
3. **Conservar**: prioridad de decisión 1–12, desambiguaciones de ingresos, manejo sí/no contextual, estado progresivo, objeciones, multi-intención, frases prohibidas (como guía de comportamiento, no como filtro de AtendIA).
4. Los formatos de cotización quedan como **guía de redacción**; los números siempre provienen de `quote.resolve` (validator lo fuerza).

### 6.3 Tool bindings (`AgentToolBinding`)
| Tool | Uso | Estado |
|---|---|---|
| `catalog.search` (SearchCatalogTool) | resolver modelo/alias/categoría, desambiguar máx 3 | ✅ existe |
| `quote.resolve` (QuoteTool) | cotización exacta por modelo+plan (sin cálculos) | ✅ existe |
| `requirements.lookup` | requisitos por plan desde KB requisitos | ✅ existe en ruta respond-style (verificar registro como tool de producto) |
| `faq.lookup` (LookupFAQTool) | FAQs | ✅ existe |
| `document.check` | clasificar/validar documento inbound (vision) | ⚠️ conectar con vision review existente (commits recientes: pymupdf render, inbound images→facts) |
| `expediente.evaluate` | evaluar completitud por plan (docs_per_plan) | ⚠️ existe `get_missing_documents`; formalizar como tool con resultado citable |
| `handoff.request` (EscalateToHumanTool) | proponer handoff con motivo | ✅ existe |
| `followup.schedule` (ScheduleFollowupTool) | proponer seguimiento | ✅ existe |

### 6.4 Modo post-handoff (D2 + blueprint)
Con `Handoff_Humano == true`: agente en modo limitado — puede responder FAQ simple sin riesgo; no negocia, no promete, no valida pagos, no cambia condiciones. Hostilidad: un mensaje breve de cierre y silencio (espera al humano). Implementación: flag en `ConversationStateRow` + policy en el ContextPackageBuilder (capabilities reducidas), **no** un composer.

### 6.5 Ruta de ejecución
El agente corre por la ruta Respond-Style (Fases 1–6 ya listas; Fase 7 ContextPackageBuilder es prerequisito). **No** se conecta vía ConversationRunner/HumanResponseComposer. Dinamo V1 es el primer tenant target de Fases 7–13 del plan Respond-Style; este documento define su configuración, no cambia esa secuencia.

---

## 7. Follow-ups (D4)

- Intentos: 1) **3 h**, 2) **12 h**, 3) **72 h** de silencio. Máximo 3 (`Followups_Enviados`).
- Horario local 7:00–23:00; fuera de horario → cola hasta ventana válida. Jitter 2–10 min.
- Cancelación: cliente responde, `Handoff_Humano`, `no_califica`, `cerrado_perdido`, `cerrado_ganado`.
- Plantillas (editables por tenant, vía `customer_message.request`):
  1. "En lugar de gastar en el camión, puedes invertirlo mejor en tu moto. Aquí estoy para ayudarte con eso."
  2. "Hola, ¿sigues en pie con tu {Moto}? {Plan_Credito_Sentence} El único paso que falta eres tú."
  3. "Te dejo abierto tu avance por aquí. Cuando quieras retomarlo, solo mándame {Siguiente_Dato_O_Documento}."
- Variables `{Plan_Credito_Sentence}` y `{Siguiente_Dato_O_Documento}` se resuelven desde estado validado (campos + expediente.evaluate), nunca improvisadas.
- UI: la pestaña Seguimientos queda como editor/monitor del workflow `followup.schedule` (activar/pausar, métricas, plantillas, pendientes, cancelar).
- **[NUEVO]** en engine: config de quiet-hours + jitter en el nodo `followup` y cancel-on-reply (hook en `message_received`).

---

## 8. Plantillas de workflow (`customer_message.request`) — única copy no-LLM

Reescritas para identidad Francisco + takeover invisible (D1/D2):

| Caso | Mensaje V1 |
|---|---|
| handoff_general | "Déjame revisarlo bien y te confirmo por aquí en un momento." |
| payment_reported | "Si ya diste enganche o hiciste un pago, eso lo reviso directo antes de mover cualquier dato. Dame un momento y te confirmo por aquí." |
| hostile_after_handoff | "Va, lo dejamos aquí por ahora. En cuanto tenga la revisión te escribo por aquí." |
| document_invalid | "Me llegó, pero así no alcanza para validarlo: {motivo}. Mándamelo completo, claro y legible para poder avanzar." |
| document_accepted_next_missing | "Perfecto, {documento_recibido} ya quedó recibido. Ahorita solo falta {documento_faltante}." |
| expediente_complete | "Perfecto, ya con eso queda tu expediente completo para revisión. Lo paso a validar; la aprobación final queda sujeta a revisión." |
| form_pending | "También llena este formulario para registrar tus datos: https://forms.gle/U1MEueL63vgftiuZ8. Cuando lo termines, avísame y paso tu expediente a revisión." |
| audio_processed | "Ya tomé lo principal de tu audio. Para avanzar sin confundirnos, solo confírmame por escrito: {siguiente_pregunta}." |
| no_califica | "Entendido, por el momento los planes para trabajadores menores a 6 meses están deshabilitados. Escríbeme cuando cumplas los 6 meses y ese mismo día te armo tu plan." |

Reglas: dedupe por (conversación, caso, ventana), pasan por SendAdapter/outbox con send_scope canónico, bloqueadas por kill switch en beta hasta abrirse.

---

## 9. Notificaciones internas (a Francisco operador)

`handoff_requested`, `payment_reported`, `expediente_complete`, `document_doubt`, `angry_customer`, `followup_failed`, `sheets_failed`, `drive_failed`, `audio_low_confidence` — todas vía `notify_agent` con dedupe. (D6: estas notificaciones + asignación sustituyen a las tareas en V1.)

---

## 10. Integraciones Google (Fase G — D3/D9)

Provisioning desde cero:
1. Proyecto GCP dedicado → service account → claves como secret **por tenant** (no en repo, no global).
2. Compartir con la service account: el Sheet de solicitudes y la carpeta raíz de Drive `/Dinamo Creditos/`.
3. **Sheets**: una fila por solicitud/cotización (`Solicitud_ID`); columnas base del mapping §9; acción de workflow `google_sheets_upsert` idempotente vía `Google_Sheets_Row_ID`.
4. **Drive**: carpeta `{telefono}_{nombre}_{fecha}` + subcarpetas `00_raw/01_aceptados/02_rechazados/03_formulario/99_notas_revision`; naming `{doc_type}_{status}_{fecha}_{short_file_id}.{ext}`; **inválidos se guardan separados y no cuentan como recibidos**.
5. **Form**: V1 detección de completado = revisión humana (`completado_manual`); webhook listo para V1.1 (`completado_webhook` vía trigger `webhook_received`).
6. Errores de integración → notificación (`sheets_failed`/`drive_failed`) + retry; **jamás** bloquean ni alteran la conversación con el cliente.

---

## 11. Orden de implementación y gates

| Fase | Contenido | Gate de salida |
|---|---|---|
| **A. Seed config** | `seed_dinamo_v1.py`: re-seed fields (D5), pipeline §3, plantillas §8, permisos §2.3 | Seed idempotente corre 2× sin duplicar; UI muestra campos/etapas correctos |
| **B. KB versionada** | Regenerar 3 JSON aprobados + hash/version + ingesta + bindings | `quote.resolve` y `requirements.lookup` devuelven datos exactos de los 34 modelos y 6 planes; conflicto DOCX vs JSON resuelto a favor del JSON |
| **C. Agente** | AgentVersion con prompt editado (§6.2), tool/field/workflow bindings, modo post-handoff | Test Lab (modo `openai_direct_provider`, no-send) pasa los escenarios núcleo de §12 |
| **D. Workflows core** | `state.write_contact_field` (con derivación enganche), `pipeline.transition`, `handoff.start`, `human.assign`, `notification.create` — todos dry-run | Trazas muestran field writes validados, transiciones correctas y handoff con takeover invisible |
| **E. Documentos (vision)** | `document.check` + `expediente.evaluate` conectados a vision review; `Docs_Checklist`/`Doc_*` solo-sistema | Documento borroso → rechazado, no cuenta; expediente completo → `Doc_Completos=true` + etapa |
| **F. Follow-ups** | quiet-hours + jitter + cancel-on-reply; plantillas §7 | 3h/12h/72h respetando horario; cancelación al responder verificada |
| **G. Google** | provisioning D9 + acciones Sheets/Drive + Form manual | Fila por solicitud actualizada; Drive válido/inválido separados; fallos → notificación sin tocar conversación |
| **H. Audio** | `audio.transcribe` → campo + turno con transcripción | Audio largo → respuesta + 1 pregunta; baja confianza → confirmación por escrito |
| **I. Beta gate** | Publish Control: single-contact **+528128889241**, kill switches (agente, workflows, followups, customer_message.request, Google), logs obligatorios | Los 18 tests del mapping §13 (ajustados a D1–D9) + §12 pasan; cero mensajes duplicados; rollback packet listo |

Dependencia externa: las fases C–I corren **no-send** hasta que la ruta Respond-Style alcance sus Fases 7–8 (ContextPackageBuilder + ProductAgentRuntime direct path). A, B, D(dry), E, F, G, H no dependen del live y pueden avanzar ya.

---

### Registro de ejecucion no-send

- 2026-06-11: Fase C provider-compat Test Lab en DB real para tenant `6ad78236-1fc9-467a-858d-90d248d57ee5`.
  - Script: `atendia.scripts.run_dinamo_phase_c_openai_compat_test_lab`.
  - Suite: `7122a1d8-f037-4c22-8d72-b96476131de5`.
  - Run: `59fab8dc-4f15-4bd2-9cb4-a103b39c2bc4`.
  - Decision: `RESPOND_STYLE_OPENAI_COMPAT_NO_SEND_READY`.
  - Coverage: `provider_class=RespondStyleLLMTurnProvider`, `execution_mode=openai_direct_provider_fake_client`, `openai_api_real=false`, `external_apis=false`, `send=no_send`, `outbox_delta=0`, `pass_count=2`, `blocked_count=0`.
  - Nota: este gate prueba compatibilidad del provider inyectando cliente local fake. La llamada real a OpenAI queda pendiente por aprobacion explicita final.
- 2026-06-12: Fase D workflows core dry-run en DB real para tenant `6ad78236-1fc9-467a-858d-90d248d57ee5`.
  - Script: `atendia.scripts.seed_dinamo_phase_d_workflows`.
  - Suite: `96fd9f06-4a6e-40b3-8283-7d447e766fea`.
  - Run: `91dd2ebc-2177-4f51-8b82-ceb810172ea2`.
  - Decision: `DINAMO_PHASE_D_WORKFLOWS_DRY_RUN_READY`.
  - Coverage: `updated_workflows=state.write_contact_field,pipeline.transition,handoff.start,human.assign,notification.create`, `openai_api_real=false`, `external_apis=false`, `send=no_send`, `outbox_delta=0`, `workflow_execution_delta=0`, `pass_count=5`, `blocked_count=0`.
  - Nota: este gate actualiza definiciones/bindings tenant-scoped a `dry_run_only` y guarda evidencia de preview. No ejecuta workflows reales ni side effects.
- 2026-06-11: Fase E documentos dry-run en DB real para tenant `6ad78236-1fc9-467a-858d-90d248d57ee5`.
  - Script: `atendia.scripts.seed_dinamo_phase_e_documents`.
  - Suite: `49615c7d-ad03-40c6-a2a8-2d2f18ab6d11`.
  - Run: `93fb626c-230b-4c63-a4c2-de6ed8358c55`.
  - Decision: `DINAMO_PHASE_E_DOCUMENTS_DRY_RUN_READY`.
  - Coverage: `updated_tool_bindings=document.check,expediente.evaluate`, `updated_field_permissions=Docs_Checklist,Doc_Incompletos,Doc_Completos`, `openai_api_real=false`, `vision_api_real=false`, `external_apis=false`, `send=no_send`, `outbox_delta=0`, `workflow_execution_delta=0`, `pass_count=4`, `blocked_count=0`.
  - Nota: este gate usa facts deterministas dry (`phase_e_dry_fact`), no vision real. La conexion `document.check` -> vision review real sigue pendiente; los campos `Doc_*` quedan solo-sistema (`expediente.evaluate`).
- 2026-06-12: Fase F follow-ups dry-run en DB real para tenant `6ad78236-1fc9-467a-858d-90d248d57ee5`.
  - Script: `atendia.scripts.seed_dinamo_phase_f_followups`.
  - Suite: `d140fa0d-967f-4a94-b362-d32be3b656c5`.
  - Run: `46e70b42-2814-4aae-886f-f2dfe6875e26`.
  - Decision: `DINAMO_PHASE_F_FOLLOWUPS_DRY_RUN_READY`.
  - Coverage: `updated_workflows=followup.schedule,customer_message.request`, `updated_bindings=followup.schedule:stage_changed,customer_message.request:customer_message.request`, `updated_field_permissions=Followups_Enviados,Proximo_Followup`, `verified_templates=dinamo_followup_3h_v1,dinamo_followup_12h_v1,dinamo_followup_72h_v1`, `openai_api_real=false`, `external_apis=false`, `send=no_send`, `outbox_delta=0`, `workflow_execution_delta=0`, `pass_count=6`, `blocked_count=0`.
  - Nota: gate D4 verificado con scheduler preview determinista: intentos 3h/12h/72h, quiet-hours 23:00-07:00 (intento de madrugada queda en cola a las 7:00), jitter 2-10 min, max 3, cancel-on-reply/handoff/etapa terminal, y fail-closed si falta variable de plantilla (nunca improvisa). El nodo `followup` real con quiet-hours+jitter+cancel-on-reply en el engine sigue siendo dry_run_only; los envios reales quedan para el beta gate (Fase I).
- 2026-06-12: Fase G Google dry-run en DB real para tenant `6ad78236-1fc9-467a-858d-90d248d57ee5`.
  - Script: `atendia.scripts.seed_dinamo_phase_g_google`.
  - Suite: `6d4a852d-a6a4-4685-be61-8eda1bbec794`.
  - Run: `32b7d3ec-7ae2-400c-b25a-da0cbfd26dc4`.
  - Decision: `DINAMO_PHASE_G_GOOGLE_DRY_RUN_READY`.
  - Coverage: `updated_workflows=google_sheets.upsert_row,google_drive.upload_file,google_form.mark_manual,notification.create`, `updated_bindings=google_sheets.upsert_row:field_updated,google_drive.upload_file:agent_document_received,google_form.mark_manual:form_completed_manual,notification.create:notification_requested`, `updated_field_permissions=Solicitud_ID,Google_Sheets_Row_ID,Google_Drive_Folder_ID,Google_Drive_File_IDs,Formulario`, `openai_api_real=false`, `google_api_real=false`, `external_apis=false`, `send=no_send`, `outbox_delta=0`, `workflow_execution_delta=0`, `pass_count=4`, `blocked_count=0`.
  - Nota: gate D9 verificado sin credenciales Google ni llamadas externas: Sheets preview idempotente por `Solicitud_ID`/`Google_Sheets_Row_ID`, Drive preview separa validos e invalidos en subcarpetas, Form V1 queda como `completado_manual`, y fallos Google generan notificacion interna preview sin alterar la conversacion. Las integraciones reales quedan bloqueadas hasta provisioning y beta gate.
- 2026-06-12: Fase H audio dry-run en DB real para tenant `6ad78236-1fc9-467a-858d-90d248d57ee5`.
  - Script: `atendia.scripts.seed_dinamo_phase_h_audio`.
  - Suite: `a3dbb1c9-f30d-49b1-b437-8092701c2623`.
  - Run: `70a1d110-b73a-4e29-a526-df492012333b`.
  - Decision: `DINAMO_PHASE_H_AUDIO_DRY_RUN_READY`.
  - Coverage: `updated_workflows=audio.transcribe,customer_message.request,notification.create`, `updated_bindings=audio.transcribe:agent_audio_received,customer_message.request:customer_message.request,notification.create:notification_requested`, `updated_field_permissions=Transcripcion_Ultimo_Audio`, `verified_templates=dinamo_audio_processed_v1`, `openai_api_real=false`, `speech_api_real=false`, `external_apis=false`, `send=no_send`, `outbox_delta=0`, `workflow_execution_delta=0`, `pass_count=3`, `blocked_count=0`.
  - Nota: gate de audio verificado sin descargar media ni llamar APIs de voz: audio largo genera transcripcion dry y una sola pregunta de avance; baja confianza marca `usable_for_agent_claims=false`, pide confirmacion por escrito y genera notificacion interna preview `audio_low_confidence`. La transcripcion real y el envio visible quedan bloqueados hasta aprobacion explicita de live/beta gate.

---

## 12. Test Lab mínimo (antes del beta gate)

Los 18 del mapping V1, con ajustes por decisiones:
1. Cliente nuevo pide crédito → pregunta antigüedad (etapa NUEVOS).
2. 2 meses trabajando → NO CALIFICA + mensaje de cierre + stop.
3. Cumple + "me pagan con tarjeta" → pregunta recibos sí/no (no asigna plan aún).
4. Sin comprobantes → `Plan_Credito=Sin Comprobantes`, `Plan_Enganche=20%` (derivado, no escrito por LLM).
5. Guardia → 30%.
6. Modelo ambiguo ("adventure") → máx 3 candidatos del catálogo real.
7. Moto+plan → cotiza con cifras exactas de `quote.resolve` **sin pedir documentos antes**.
8. Cambia moto antes de pagar → recotiza conservando plan/enganche.
9. Documento borroso → rechazado (Drive `02_rechazados`), pide corrección, no cuenta.
10. Todos los documentos → PAPELERÍA COMPLETA + notificación.
11. "Ya pagué" → handoff inmediato, motivo `pago_reportado`, mensaje takeover invisible (sin "te paso con…").
12. Pide humano → handoff + asignación + notificación, identidad intacta.
13. Insulta tras handoff → un mensaje breve y silencio.
14. Silencio → follow-ups 3h/12h/72h, máx 3, fuera de horario en cola.
15. Audio largo → transcripción + respuesta + una sola pregunta.
16. Drive separa válido/inválido.
17. Sheets una fila por solicitud.
18. Conflicto DOCX vs JSON → gana JSON aprobado.

Extra obligatorios (de los transcripts fallidos y CLAUDE.md):
19. Multi-intención ("puedo liquidar antes? checan buró? ubicación") → responde todo con fuente + 1 pregunta de avance.
20. "Sí/la primera" contextual resuelve la última pregunta del bot.
21. Estado progresivo: nunca re-pregunta antigüedad/plan/modelo ya guardados.
22. Enganche inexistente para esa moto → fail-closed + handoff, sin inventar.
23. Cero leaks internos (nombres de tools, variables, trazas) en `final_message`.
24. La IA jamás escribe `Autorizado` ni mueve a CERRADO GANADO (intento → bloqueado por permiso, trazado).
25. Cliente pide plazo distinto ("¿puedo pagarlo a 1 año?", "¿menos quincenas?") → responde que el esquema es de 72 quincenas con liquidación anticipada sin penalización (FAQ_004/006/010); si insiste en excepción → handoff `excepcion_no_cubierta` (D10).

---

## 13. Riesgos principales

| Riesgo | Severidad | Mitigación |
|---|---|---|
| Identidad Francisco + takeover invisible: cliente pregunta "¿eres bot?" | Media | Política de respuesta honesta-suave definida en prompt (no negar agresivamente, redirigir a avance); el humano real responde igual. Revisar en Test Lab. |
| `Plan_Enganche` escrito libre por el LLM (ej. guardia pidiendo 10%) | Alta | Campo no escribible por agente; derivación fija en workflow + validator. Test 5 y "pero como guardia quiero el 10%". |
| Workflows con copy visible fuera de la vía única | Alta | Solo `customer_message.request` con plantillas registradas; smoke gate de send_scope canónico ya existente. |
| Google integration falla y rompe conversación | Media | Integraciones asíncronas post-turno; fallo → notificación + retry, nunca bloquea respuesta. |
| Vision acepta documento ajeno (estado de cuenta de la esposa) | Alta | `document.check` extrae titular y compara contra contacto; duda → `document_doubt` + handoff, no aceptar. |
| Re-seed rompe fixtures/tests existentes que asumen el seed viejo | Media | Buscar referencias a `plan_credito` (plazos 12m/24m — valores inventados que no existen en el negocio, D10) en fixtures/simulación antes del re-seed; actualizar `dinamo_fresh_tenant_v1.yaml`. |
| Confundir no-send con live | Alta | Gate I exige los kill switches activos y el número beta exacto; live-limited solo tras 18+6 tests y cero duplicados. |

---

## 14. Pendientes abiertos (no bloqueantes de Fases A–B)

1. Definir `Plan_Credito_Sentence` exacto para follow-up 2 (plantilla por plan).
2. Confirmar usuario operador real de Francisco en el tenant (para `assigned_user_id` y notificaciones).
3. Decidir si `Vive_o_Trabaja_NL=no` dispara NO CALIFICA automático o solo handoff (Flujo sugiere "no avanzar normal" → V1: handoff con motivo `fuera_de_nl`).
4. V2: entidad Task real, webhook de Google Form (`completado_webhook`), alias de campos como feature de plataforma, tipo `catalog_item`.
