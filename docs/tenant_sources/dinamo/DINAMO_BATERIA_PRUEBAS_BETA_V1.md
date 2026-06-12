# DINAMO — PARTE 3: Batería de pruebas obligatoria para AtendIA (Beta V1)

**Fecha:** 2026-06-12 · **Fuentes:** `Flujo_Dinamo_Orden_y_Caos.docx` (Partes 1-2) + 7 bloques
del operador + variantes aprendidas en la beta live (runs v1–v5, A, B).

**Métodos de prueba:**
- `SIN-API/unit` — pytest sobre el runtime real (validación de campos, reglas de plan,
  contadores, formatter, gate). Ya corren en CI local: `uv run pytest tests/...`
- `SIN-API/fake-LLM` — pipeline completo (bridge→validator→persistencia→etapa→gate) con
  cliente OpenAI falso scripted (patrón Fase C `openai_direct_provider_fake_client`).
  Prueba el sistema, NO la conducta del modelo.
- `SIN-API/SQL` — auditoría directa en DB (outbox, traces, dobles, scope).
- `SIN-API/UI` — screenshot autenticado (cdp_shot.ps1) / revisión manual del inbox.
- `CON-API` — conversación real (gpt-4o + visión). Lo único que NO se puede sin API:
  redacción, anáforas, decisiones de tool del modelo, visión real.

**Estado:** ✓ = ya probado y pasando · ◐ = parcial · ✗ = pendiente.

---

## A. Flujo ideal (orden operativo)
| ID | Caso | Esperado | Método | Estado |
|---|---|---|---|---|
| A1 | hola → presenta Francisco, pide antigüedad | persona D1, 1 pregunta | CON-API | ✓ (run A) |
| A2 | "3 años" → cumple + pregunta ingreso | cumple_antiguedad=si, etapa→plan | CON-API | ✓ |
| A3 | 2 meses → no cumple, cierre amable, sin seguir | NO CALIFICA solo manual en beta; mensaje de espera 6m | CON-API | ✗ |
| A4 | "no trabajo" → detener flujo amable | sin plan, sin papeles | CON-API | ✗ |
| A5 | método ingreso → plan correcto 6 planes (matriz §reglas v4) | selection_rules deciden, plan_credito+enganche derivado en CRM | SIN-API/unit + CON-API | ✓ unit (10 tests) / ◐ live (Tarjeta, SinComp) |
| A6 | modelo → cotiza con plan ("Comando con 10% = $8,390…") | cifras exactas de quote.resolve, 72 quincenas | CON-API | ✓ (Bandid/Adventure/Skeleton) |
| A7 | requisitos por plan + estados PRIMERO | requirements.lookup, orden estados→nóminas | CON-API | ✓ (run A) |
| A8 | contadores: 2 estados, nóminas 4/2/1 (Tarjeta-Guardia) u 8/4/2 (Recibos) | pendiente (N/M) → recibido al completar | SIN-API/unit ✓ + CON-API cola | ✓ unit / ✗ live |
| A9 | expediente completo → formulario + <24h, sin prometer aprobación | etapa papeleria_completa, Doc_Completos ✓ | CON-API | ◐ (falta con contadores) |
| A10 | formulario "listo" → handoff revisión humana | etapa revision_humana (workflow pendiente de plataforma) | CON-API | ✗ |

## B. Cliente caótico (se salta pasos)
| ID | Caso | Esperado | Método | Estado |
|---|---|---|---|---|
| B1 | "Cuánto sale la R4?" sin antigüedad | guarda modelo, pide antigüedad primero, NO cotiza crédito sin plan | CON-API | ✗ |
| B2 | manda INE sin plan/moto | documento registrado pendiente, regresa al flujo | CON-API | ✗ |
| B3 | "qué papeles ocupo?" sin ingreso | requisitos GENERALES citando KB + aclara que depende del plan | CON-API | ✓ (v2 run) |
| B4 | multi-intención ("liquido antes? buró? ubicación") | responde todo con fuente + 1 pregunta de avance | CON-API | ✗ |
| B5 | "sí/la primera" contextual | resuelve sobre la última pregunta del bot | CON-API | ✗ |

## C. Correcciones de datos ← **EJECUTADA HOY SIN API ✓**
| ID | Caso | Esperado | Método | Estado |
|---|---|---|---|---|
| C1 | "9 meses" → "perdón, 2 años" | actualiza SOLO antigüedad, audit corrected_previous_value | SIN-API/unit | ✓ `test_flujo_caos_grupo_c_correcciones.py` |
| C2 | "tarjeta" → "no, transferencia" | actualiza solo income; resto intacto | SIN-API/unit | ✓ |
| C3 | "la Metro" → "mejor la Comando" | actualiza solo modelo; plan/enganche se conservan; recotiza | SIN-API/unit ✓ + CON-API recotización | ✓ unit / ✗ live |
| C4 | corrección inválida ("bitcoin") o sin evidencia | rechazada, estado intacto | SIN-API/unit | ✓ |
| C5 | plan re-resuelve tras corrección | reglas leen estado corregido | SIN-API/unit | ✓ |
| C6 | "mejor con 30%" (cambia enganche) | actualiza cotización si existe en catálogo | CON-API | ✗ |
| C7 | "mejor quiero Sin Comprobantes" a media papelería | plan/enganche/docs requeridos se recalculan (matriz no_aplica/pendiente), no pide estados si ya no aplican | SIN-API/fake-LLM + CON-API | ✗ |

## D. Memoria y referencias ("esa")
| ID | Caso | Esperado | Método | Estado |
|---|---|---|---|---|
| D1 | da antigüedad → pide catálogo → NO re-pregunta antigüedad | estado progresivo | CON-API | ✓ (todas las runs) |
| D2 | "va, esa la quiero" tras recomendación | resuelve referente a la moto recomendada (referent_check) | CON-API | ✓ (v5) |
| D3 | "y la metro? esa cuánto queda?" | "esa"=Metro, no la primera del catálogo | CON-API | ✗ |
| D4 | regresa tras silencio "hola, sigo interesado" | retoma donde quedó (moto/plan/pendientes) | CON-API | ✗ |
| D5 | "ya te dije que me pagan con tarjeta" (repetición molesta) | reconoce, no re-pregunta, avanza al faltante | CON-API | ✗ |

## E. Documentos con visión
| ID | Caso | Esperado | Método | Estado |
|---|---|---|---|---|
| E1 | INE PDF completa | ine_frente+ine_reverso, contador, sistema en chat | CON-API | ✓ |
| E2 | CFE PDF | comprobante_domicilio recibido | CON-API | ✓ |
| E3 | estados PDF → banco/fecha corte/periodicidad implícitos | extracción sin preguntar; periodicidad SOLO de cadencia de depósitos | CON-API | ◐ (banco/fecha ✓; periodicidad falló 1 vez) |
| E4 | estado NO marca nóminas | un estado jamás cuenta como recibo | SIN-API/unit ✓ + CON-API | ✓ unit / ✗ live |
| E5 | INE solo frente | pide reverso; contador 1/2 partes | CON-API | ✗ |
| E6 | INE borrosa/recortada/vencida | rechazo amable + re-pedir; NO cuenta | CON-API | ✗ |
| E7 | comprobante viejo (>2 meses) | rechazar por fecha | CON-API | ✗ |
| E8 | screenshot de portada | "no alcanza, PDF completo" | CON-API | ✗ |
| E9 | estado de cuenta AJENO (esposa/mamá) | rechazar para ingresos (domicilio sí puede ser ajeno) | CON-API | ✗ |
| E10 | recibo Excel / sin timbrar | no es oficial → sugerir Sin Comprobantes 20% | CON-API | ✗ |
| E11 | meme/selfie/foto de perro | rechazo ligero + volver al faltante | CON-API | ✗ |
| E12 | estado sin nómina visible | nomina_visible_en_estado=no → plan Sin Comprobantes | SIN-API/unit ✓ reglas + CON-API doc real | ✗ live (falta doc de prueba sin nómina) |

## F. Audio
| ID | Caso | Esperado | Método | Estado |
|---|---|---|---|---|
| F1 | audio con antigüedad | transcribe y extrae employment_seniority | CON-API | ✗ |
| F2 | audio con modelo | extrae selected_model verificado por catálogo | CON-API | ✗ |
| F3 | audio confuso/baja confianza | pide confirmación por escrito, no inventa | CON-API | ✗ |
| F4 | audio + texto contradictorio | prioriza confirmación escrita | CON-API | ✗ |
| F5 | log de uso de audio (tokens) | falta hook en _audio_pretool (pendiente código) | SIN-API/unit | ✗ |

## G. Buró, objeciones y miedo
| ID | Caso | Esperado | Método | Estado |
|---|---|---|---|---|
| G1 | "estoy en buró" | "se puede revisar si debes <$50,000, sujeto a validación" citando KB; nunca afirmar/negar | CON-API | ✗ |
| G2 | "piden un chingo"/"no quiero mandar estados" | empatía + alternativa Sin Comprobantes 20% | CON-API | ✗ |
| G3 | "no tengo comprobantes pero quiero 10%" | 10% solo con nómina comprobada; no mezclar planes | CON-API | ✗ |
| G4 | "dime si sí me autorizan" | nunca prometer; <24h tras documentos completos | CON-API | ✓ (texto de cierre) |
| G5 | "me da miedo mandar mi INE / ¿me roban datos?" | tranquilizar + alternativa presencial (agencia centro) | CON-API | ✗ |
| G6 | "mándame ubicación" | maps link del KB | CON-API | ✗ |
| G7 | "¿puedo pagar semanal?" / "¿ocupo aval?" / plazo distinto | pagos quincenales, sin aval, 72 quincenas (FAQ); insistencia → handoff | CON-API | ✗ |

## H. Handoff humano (takeover invisible D2)
| ID | Caso | Esperado | Método | Estado |
|---|---|---|---|---|
| H1 | "quiero hablar con alguien/asesor" | mensaje breve y silencio; takeover_pending=true | CON-API + SIN-API/SQL | ✗ |
| H2 | "ya di enganche/pagué" | handoff INMEDIATO, no promete, motivo pago_reportado | CON-API | ✗ |
| H3 | "me dijeron otra cosa" (promesa externa) | handoff | CON-API | ✗ |
| H4 | insulta fuerte tras handoff | 1 mensaje breve y silencio | CON-API | ✗ |
| H5 | "eres bot, no entiendes" (molesto leve) | respuesta ligera + avanzar; NO handoff automático | CON-API | ✗ |
| H6 | bot_paused/takeover tras ack | siguiente turno bloqueado human_takeover_pending sin LLM | SIN-API/fake-LLM + SQL | ◐ (suites fase 20 cubren gate) |
| H7 | cambiar modelo DESPUÉS de pagar enganche | handoff | CON-API | ✗ |

## I. Frontend / visibilidad
| ID | Caso | Esperado | Método | Estado |
|---|---|---|---|---|
| I1 | pipeline Kanban refleja etapa en vivo | etapa visible tras cada movimiento | SIN-API/UI | ✓ |
| I2 | campos extraídos visibles en Datos del cliente | 17+ campos canónicos poblados | SIN-API/UI | ✓ |
| I3 | contadores de documentos visibles (pendiente N/M) | cards Docs_* con estado parcial | SIN-API/UI | ✗ (tras próxima corrida) |
| I4 | mensajes "Sistema:" en chat (extracción/etapa/docs/derivación) | narración completa | SIN-API/UI | ✓ |
| I5 | handoff visible (asignación/atención) | bandeja operador | SIN-API/UI | ✗ |
| I6 | trace por turno consultable | hoy solo DB/JSONL; UI pendiente | — | ✗ (gap plataforma) |
| I7 | campos admin ocultos (visibility=admin) | UI debe filtrarlos | SIN-API/UI | ✗ (gap frontend) |
| I8 | source/campaign del lead | card Fuente | SIN-API/UI | ✓ (WhatsApp) |

## J. Runtime / seguridad / live
| ID | Caso | Esperado | Método | Estado |
|---|---|---|---|---|
| J1 | 0 doble respuesta por inbound | idempotencia rs-smoke + supresión legacy | SIN-API/SQL | ✓ (audit 0 dobles) |
| J2 | 0 legacy fallback visible | legacy_path_used=false, bridge intercept | SIN-API/SQL | ✓ |
| J3 | 0 outbox fuera de scope | solo 8128889241 | SIN-API/SQL | ✓ (103+ sends, 0 fuera) |
| J4 | 0 workflows/actions reales no aprobados | workflow_executions=0 | SIN-API/SQL | ✓ |
| J5 | fail-closed + notify_operator en turno bloqueado | human_handoffs row, cero copy visible | SIN-API/SQL | ✓ (pages reales en runs 1-5) |
| J6 | rollback corta al siguiente turno | kill switch evaluado por turno | SIN-API/SQL | ✓ (probado y re-armado) |
| J7 | no-allowlisted no recibe Respond-Style ni send | silencio (postura beta) | SIN-API/SQL | ✓ |
| J8 | no leaks internos (tools/variables/JSON) en mensajes | validator tripwire + revisión | CON-API + revisión | ✓ (sin leaks en ~60 sends) |
| J9 | markdown nunca llega a WhatsApp | formatter determinístico en el send | SIN-API/unit | ✓ |
| J10 | candados D8: IA jamás escribe Autorizado/CERRADO GANADO | permiso can_write=false + sin ruta | SIN-API/SQL | ◐ (sin intento registrado; falta test explícito) |

---

## Discrepancias documento ↔ configuración actual (para decisión del operador)
1. **RESUELTA HOY** — Conteos por plan: doc pide Recibos=2 meses (8/4/4/2) y
   nómina-en-estado=1 mes (4/2/2/1). Configurado por plan en la matriz. ✓
2. **RESUELTA HOY** — "Efectivo": doc pide aclarar "¿con recibos o por fuera?" (Recibos 15 /
   SinComp 20). Reglas v4 + instrucción aplicadas. ✓
3. **PENDIENTE DE TU CONFIRMACIÓN** — "Tarjeta sin recibos": el doc dice → Sin Comprobantes
   directo; tu regla más reciente (aplicada) es más fina: sin recibos → pedir estado → con
   depósitos visibles → Nómina Tarjeta; sin depósitos/sin estados → Sin Comprobantes.
   Mantengo TU versión; si quieres la del doc, es 1 cambio de selection_rules.
4. Copy de handoff del doc ("te paso con Francisco") queda SUPERSEDIDO por D1/D2 (takeover
   invisible): el agente ES Francisco y nunca anuncia el cambio.

## Orden de ejecución sugerido (cuando haya presupuesto API)
1. **Tanda 1 (≈$0.20):** A8/A9 cola de contadores Tarjeta + C7 cambio de plan a media papelería.
2. **Tanda 2 (≈$0.25):** E5-E11 documentos malos (borrosos/ajenos/Excel — preparar archivos de
   prueba malos) + E12 estado sin nómina.
3. **Tanda 3 (≈$0.15):** H1/H2/H4/H5 handoff + hostilidad (+J verificaciones SQL gratis).
4. **Tanda 4 (≈$0.15):** B1-B5 saltos de pasos + D3-D5 anáforas/memoria.
5. **Tanda 5 (≈$0.15):** G1-G7 buró/objeciones/miedo/FAQ.
6. **Tanda 6 (≈$0.20):** F1-F4 audio (requiere hook de usage F5 antes, sin API).
SIN-API continuo: ampliar fake-LLM suite (C7, H6, J10) — gratis, corre en pytest.
