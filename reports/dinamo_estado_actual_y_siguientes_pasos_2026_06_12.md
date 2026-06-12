# Dinamo / AtendIA — Estado actual, auditoría y siguientes pasos (2026-06-12)

Para: Felipe. Resumen operativo tras la beta live limitada (runs v1–v5) y la tanda de fixes
sin API de esta noche. Léelo de arriba hacia abajo: primero qué se arregló, luego la
auditoría de qué es modificable y qué no, costos, y el siguiente paso.

---

## 1. Fixes de esta tanda (SIN API — pendientes de 1 conversación de verificación)

| # | Problema que señalaste | Fix | Tipo |
|---|---|---|---|
| 1 | `**negritas**` visibles en WhatsApp (imagen 1) | Normalizador determinístico antes del envío: `**x**`→`*x*`, `[texto](url)`→`texto: url`, sin headers. Ya no depende de que el LLM obedezca. | Código (formatter genérico + tests) |
| 2 | Personalidad: parecía máquina, ofrecía "conectar con humano" | Persona = **Francisco de Dinamo Motos NL**; prohibido decir asistente digital/IA/bot u ofrecer humano por iniciativa; handoff SOLO si piden persona/asesor o están molestos → mensaje breve y **silencio esperando al humano** (mecanismo nativo ya existente) | Config (instructions) |
| 3 | "No me dan recibos" → asignó plan Nómina | Ya NO asigna plan con eso: pide el estado de cuenta ("con tus depósitos lo definimos"). El plan se decide con evidencia del documento: depósitos de nómina visibles → **Nómina Tarjeta**; no visibles → **Sin Comprobantes**. Reglas determinísticas nuevas (campo `nomina_visible_en_estado` que llena la visión) | Config (selection_rules + regla) + código menor |
| 4 | No confirmar depósitos al cliente sin documento | Regla 27: jamás afirmar datos de documentos que no vengan de un `document.review` real de esa conversación | Config |
| 5 | Periodicidad tomada del ciclo del estado (salió "mensual") | Visión instruida: periodicidad SOLO de la cadencia de depósitos de nómina (~7 días=semanal, ~15=quincenal) o del periodo del recibo; si es dudosa → null y el campo no se escribe | Código (prompt visión) + config |
| 6 | Doc Completos "Sin dato" aunque el chat dijo completo | `Doc_Completos` ahora se llena desde `expediente_estado` (completo→✓) vía coerción configurable | Código (coerción) + config |
| 7 | Recomendaciones de moto | Por categorías: mínimo 4 (deportiva, naked, chopper + motoneta/urbana o trabajo) con 2 modelos reales por categoría desde `catalog.search` (límite subido a 8 resultados), variando modelos entre conversaciones; cierre con **ambos links**: https://dinamomotos.com/catalogo y https://wa.me/c/5218186016492 | Config + código menor |

Verificación hecha sin API: ruff limpio, **46 tests** pasando (incluye suites del gate de envío).

### Suposiciones que debes confirmarme
1. **"No me dan recibos"** → sin plan hasta ver estado de cuenta (depósitos visibles ⇒ Nómina
   Tarjeta; no visibles ⇒ Sin Comprobantes). *(Así lo dejé.)*
2. **"Tengo que pedirlas"** (recibos obtenibles) → sigue yendo directo a Nómina Tarjeta
   tentativo. ¿O también debe esperar el estado?
3. **Pensionados / Guardia de Seguridad**: hoy el agente no tiene señales para detectarlos
   ("soy pensionado", "soy guardia"). Puedo agregar valores a income_type + reglas + requisitos
   (resolucion IMSS / 30% guardia). Dime si lo quieres en la siguiente tanda.
4. El link web del catálogo lo dejé EXACTO como lo escribiste: `https://dinamomotos.com/catalogo`.

---

## 2. Auditoría: qué es modificable y cómo

### A. Modificable SIN código (config en DB — tú o yo, efecto inmediato por turno)
- **AgentVersion v12** (el "cerebro configurable"): instrucciones/persona, campos que el LLM
  puede extraer (`field_policy` con allowed_values), tools y sus precondiciones +
  `selection_rules` del plan + `max_results`, snippets de conocimiento (links, formulario,
  política de proceso), hard policies (regex de qué exige fuente: precios, requisitos,
  elegibilidad, catálogo).
- **Definiciones de campos del CRM** (`customer_field_definitions`): labels, orden, aliases
  (mapeo runtime→CRM), choices, derivaciones (Plan_Enganche←Plan_Credito), matriz de
  documentos (`required_for_plans`/`received_from`), true/false_values.
- **Pipeline** (`tenant_pipelines.definition`): etapas, reglas de auto-entrada, docs por plan.
- **Deployment** (flags): allowlist del beta, modelo (`respond_style_model`), kill switch,
  `respond_style_stage_movement_enabled`, `respond_style_canonical_fields_enabled`.
- **KB datasets**: catálogo (34 motos, precios pre-calculados), requisitos por plan, FAQ.

### B. Modificable CON código (runtime compartido, genérico — requiere tests + cuidado)
- Validador (semántica de claims/policies), executor de tools, prompt de visión, formatter
  WhatsApp, evaluador de pipeline, persistencia canónica, log de uso. Todo lo de esta sesión
  vive aquí, **flag-gated**: apagado para cualquier otro tenant.
- **Workflows del engine** (followups reales, Google Sheets/Drive, plantillas): ejecutarlos
  real NO es un flip — falta el emisor de eventos en la ruta nueva y reescribir definiciones.
  El handoff real ya funciona por fuera del engine.

### C. NO tocar sin proceso explícito
- Gate de envío Fase 20 (columnas canónicas + texto de aprobación literal + allowlist).
- Candados D8: `Autorizado` y CERRADO GANADO solo humano/admin.
- Runner legacy (crashea cuando corre, pero está estructuralmente suprimido; arreglarlo es
  proyecto aparte, no parche).

### D. Frontend: qué se ve, qué está oculto y por qué
| Elemento | Estado |
|---|---|
| Chat con mensajes de Sistema (extracciones, etapa, docs) | ✅ visible |
| Datos del cliente: 38 campos canónicos (incl. matriz Docs_*) | ✅ visible, editable; orden = `ordering` (config) |
| Etapa (editable) + Kanban | ✅ visible |
| Plan Crédito | ✅ visible (era bug de alias legacy, corregido) |
| Panel "Campos del tenant" | 🗑️ removido a tu pedido |
| Cards legacy (Tipo de crédito viejo, etc.) | Ocultas: solo aparecen en tenants sin metadata (modo legacy) |
| Shadow fields del runtime | Ocultos a propósito: estado interno; su espejo canónico es lo visible |
| Campos admin (Solicitud_ID, Google_*, Source_Version_ID) | ⚠️ hoy se ven; el plan dice ocultarlos con `visibility:"admin"` — falta que la UI filtre (cambio frontend pequeño) |
| Trazas por turno / validator / tokens | Solo DB y JSONL; no hay UI de auditoría por turno (pendiente) |

### E. ¿Sirve para otros nichos?
**Sí.** Todo lo Dinamo vive en config: el runtime no tiene un solo hardcode del giro
(auditado con rg). Para clonar a otro nicho: (1) definiciones de campos canónicos, (2)
AgentVersion (persona+campos+tools+reglas de selección del "plan"/oferta+snippets), (3)
pipeline con auto-entrada, (4) datasets reales para las tools (`real_source`:
catálogo/planes/FAQ), (5) matriz de documentos si aplica, (6) deployment + allowlist beta.
Las tools son genéricas de venta asistida (buscar catálogo, resolver oferta, requisitos,
cotizar); la visión clasifica documentos genéricos (identificación/domicilio/estado/recibo).

---

## 3. Costos (medidos, no estimados) y cómo bajarlos

Run v5 medido con la instrumentación nueva (`core/uploads/llm_usage/*.jsonl`, una línea por
request con tokens y `test_run_id`):

- **$0.295 USD ≈ 5.4 MXN por conversación completa** (13 mensajes del cliente, 4 documentos
  con visión, hola → expediente completo). 22 requests; 73% del input ya sale cacheado.
- 1,000 conversaciones ≈ **$295 USD ≈ 5,400 MXN** → tu cuenta es correcta y hoy es más caro
  que respond.io (~3,000 MXN).

Desglose real del costo: input cacheado $0.146 + input nuevo $0.108 + output $0.041.

### Palancas de ahorro (en orden de impacto/esfuerzo)
1. **Visión con gpt-4o-mini + detail bajo** (config/código menor): la clasificación de
   documentos no necesita 4o. Ahorro ~20-25% del total. Riesgo bajo; validar con los PDFs de
   Docs prueba en Test Lab.
2. **Dieta de contexto** (config): las instrucciones ya van en ~10k chars + snippets + 27
   reglas. Consolidarlas (mismo contenido, menos palabras) recorta el costo BASE de cada
   request (incluso el cacheado se cobra). Ahorro estimado 15-25%.
3. **Transcript cap**: limitar el historial enviado por turno (hoy crece con la conversación).
4. **gpt-4o-mini en turnos simples** (código: router por tipo de turno): saludos, "ok",
   despedidas no necesitan 4o. Ahorro adicional ~20-30%. Riesgo medio (decidir bien cuándo).
5. **No degradar el modelo de conversación completo a mini**: las referencias ("esa la
   quiero"), el plan tentativo y las reglas duras son justo donde mini falla. No lo recomiendo
   sin un A/B serio en Test Lab.

**Proyección realista**: con (1)+(2)+(3) → **~$0.15-0.18 USD ≈ 2.8-3.3 MXN/conversación**
(par con respond.io pero con tu propio runtime). Con (4) bien hecho → **~$0.10-0.12 ≈ 2 MXN**.
Además: el costo real por LEAD es menor — no toda conversación llega a documentos+visión.

### APLICADO 2026-06-12 (tanda "2 pesos", sin API — pendiente medir en la verificación)
- ✅ Palanca 1: visión en **gpt-4o-mini** (`respond_style_vision_model` en deployment;
  detail configurable, se mantuvo high para leer fechas/bancos). Visión pasa de ~$0.06 a ~$0.004.
- ✅ Palanca 2: instrucciones reescritas compactas — **11,600 → 6,199 chars (-47%)** del costo
  base de CADA request, mismo comportamiento validado.
- (3) transcript ya estaba acotado a 12 mensajes — no era palanca.
- Proyección de la próxima medición: **~$0.13-0.16 USD ≈ 2.4-3.0 MXN**. El último tramo a
  ~2 MXN es el router de modelo por tipo de turno (proyecto pequeño de código, no parche).

**MEDIDO (runs A+B, post-palancas):** $0.298 USD por AMBAS corridas (15 mensajes de cliente:
A=Nómina Tarjeta completa con 4 documentos $0.26, B=ruta Sin Comprobantes $0.04). Hallazgos:
(a) el caché cayó a 27% en esta medición porque cambié config a media corrida y hubo pausas
>5 min entre turnos (el caché de OpenAI expira) — en operación continua regresa a ~70%;
(b) **quirk de mini-visión**: gpt-4o-mini infla ~33x los tokens de imagen (228k tokens por 4
documentos), así que el ahorro real de visión fue ~30%, no 15x — la palanca correcta es
`respond_style_vision_detail=low` y/o bajar el dpi del render (ya configurable). Con caché
estable + detail low, la proyección ~2.5-3.5 MXN/conversación completa se sostiene.

### Reglas de plan v3 (aplicadas, filosofía "plan final = evidencia")
1. Guardia de seguridad (`es_guardia=si`) → **Guardia de Seguridad 30%** (prioridad máxima).
2. `income_type=pensionado` → **Pensionados**.
3. Recibos disponibles → Nómina Recibos. 4-5. Recibos **por pedir** → tentativo Nómina
   Tarjeta + pide UNA nómina oficial de muestra: válida (`nomina_oficial_valida=si`) confirma;
   inválida → **Sin Comprobantes 20%**. 6-7. **No le dan recibos** → sin plan hasta el estado
   de cuenta: depósitos visibles → Nómina Tarjeta; no → Sin Comprobantes. 8-10. Negocio
   con/sin SAT → Negocio SAT / Sin Comprobantes; efectivo → Sin Comprobantes.
   Simulación sin API: 10 tests unitarios de reglas (guardia/pensionado/muestra incluidos).

### Disciplina de medición (ya instalada)
Antes de cada prueba: escribe el id en `core/uploads/llm_usage/RUN_ID` (o env
`ATENDIA_TEST_RUN_ID`), anota hora/modelo; al final, el JSONL te da requests y tokens exactos
para cruzar con OpenAI Usage. El reporte v5 quedó como plantilla en
`reports/screenshots_dinamo_v5_2026_06_12/99_metricas_final.txt`.

---

## 3.5 Tanda contadores (12-jun, sin API — pendiente verificación live)

Feedback del operador tras runs A/B:
1. **Contadores reales por documento**: `Docs_Estados_Cuenta` exige 2 distintos
   (`estado_cuenta_marzo`, `estado_cuenta_abril`); `Docs_Recibos_Nomina` exige según
   periodicidad (semanal=4, quincenal/catorcenal=2, default 4). Recibir 1 de 4 deja el campo
   en `pendiente (1/4)` con nota de sistema; "recibido" SOLO al completar el conteo. El mismo
   documento repetido no suma.
2. **Un estado de cuenta jamás cuenta como nómina**: se eliminó `Docs_Nomina_En_Estado` (el
   falso-positivo venía de la visión); la evidencia de depósitos para el PLAN sigue siendo
   `nomina_visible_en_estado`, pero las nóminas como DOCUMENTOS se cuentan una por una.
3. **Persistencia idéntica en TODOS los caminos**: la tubería (aliases→canónico, derivación,
   matriz) siempre fue una sola para todos los planes; el hueco de Run B era que el LLM
   "sugirió" Sin Comprobantes sin llamar la tool ni proponer `plan_credito`. Ahora es regla
   dura: determinar/confirmar/cambiar plan por CUALQUIER camino ⇒ `credit_plan.resolve` en ese
   turno + proponer `plan_credito` — "un plan dicho sin tool ni campo no existe".
   (La antigüedad perdida en Run B fue un bug de encoding de mi comando de prueba, no del sistema.)
4. Nota: expediente completo SOLO con todos los contadores llenos; con avance parcial el
   agente reconoce "va 1 de 4" y dice cuáles faltan.

Pendiente de verificar con API (1 corrida): cola de Nómina Tarjeta con contadores
(estados 2/2 → pide 4 o 2 nóminas → 1/4 → … → completo + formulario) y Sin Comprobantes
persistiendo plan+enganche en CRM.

## 4. Siguiente paso (cuando me digas)

1. **1 conversación de verificación (~$0.30 USD)** del paquete de esta noche: saludo Francisco,
   catálogo por categorías con ambos links, "no me dan recibos" → pide estado → plan según
   depósitos, sin `**`, periodicidad correcta, Doc Completos ✓. Con screenshots a carpeta.
2. Si pasa → decidir entre: (a) palancas de costo 1-2-3, (b) `expediente.evaluate`
   determinístico (que la completitud de papelería no la juzgue el LLM), (c) pensionados/
   guardia, (d) UI: ocultar campos admin + label legible de Moto ("Renegada 250 CC" en vez de
   `renegada_250_cc`).
3. Más adelante (proyectos, no parches): followups reales (Fase F), Google Sheets/Drive
   (Fase G), audio (Fase H), ampliar allowlist beta (con respuesta para no-allowlisted, hoy
   reciben silencio).

**Importante**: el gate sigue armado — tu teléfono recibe respuestas reales. Kill switch en el
reporte principal (`reports/dinamo_beta_live_credit_flow_review_2026_06_12.md`, §12).
