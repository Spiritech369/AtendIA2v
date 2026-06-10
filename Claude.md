Actúa como arquitecto principal de plataformas de agentes IA multi-tenant tipo Respond.io, Intercom, HubSpot, OpenAI Agents, Claude Code y sistemas de runtime agentic con tool calling, RAG, workflows, CRM fields, WhatsAppinbox, Test Lab, Publish Control y migración legacy.

Necesito una revisión brutal de arquitectura. No quiero fixes pequeños. No quiero optimismo falso.

Contexto general

Estoy construyendo AtendIA, una plataforma de agentes IA para WhatsAppinbox con

 agentes configurables por tenant
 promptpersonainstrucciones
 Knowledge Base
 tools internas
 actionsAPI externas
 workflowstriggers
 extracción y escritura de contact fields
 pipelinestages
 handoff humano
 Test Lab
 Publish Control
 no-sendliverollback
 auditoría por turno

Objetivo final

No quiero un bot de ifs.
No quiero composers escribiendo customer copy.
No quiero policies conversacionales disfrazadas de inteligencia.
No quiero blocked phrase lists como estrategia principal de calidad.
No quiero legacy viviendo en la ruta publicada.
No quiero que AtendIA actúe como guionista.

Quiero esto

LLM conversa.
AtendIA orquesta, valida, guarda campos, ejecuta toolsactionsworkflows permitidos, audita y decide sendno-send.

Separación deseada

El LLM debe

 entender la conversación
 redactar el mensaje visible
 manejar objeciones
 pedir datos faltantes naturalmente
 proponer tool calls
 proponer field updates
 proponer workflow triggers
 proponer handoff
 decidir el siguiente paso conversacional

AtendIA debe

 cargar configuración del agente
 recuperar KB
 preparar contexto
 exponer toolsactionsworkflows como capabilities
 ejecutar tools fact-only
 validar facts
 validar campos
 validar permisos
 guardar contact fields
 ejecutar triggers permitidos
 controlar sendno-send
 auditar todo

AtendIA NO debe

 escribir customer copy con ifs
 reparar conversación con plantillas
 decidir frases humanas
 convertir pending_slot en pregunta automática
 usar fallbacks visibles como respuesta al cliente
 permitir workflowcustomer-copy fuera del runtime validado

Estado actual del proyecto

Ya existe una auditoría completa del repo

1. `AUDITORIA_COMPLETA_ATENDIA_2026_06_09.md`

La auditoría encontró

 AtendIA ya tiene muchas piezas reales.
 Backend FastAPI multi-tenant.
 Inboxconversationsmessages.
 Customerscontact fields.
 Meta webhook y Baileys bridge.
 Workflowseventosaudit logrealtime.
 Outbox.
 Knowledge OS.
 Runtime V2 con AgentService.
 Semantic Interpreter.
 Tool layer tenant-aware.
 StateWriter.
 HumanResponseComposer.
 PolicyValidator.
 Universal turn trace.
 Product Agent Builder.
 Product agent entities.
 Toolaction bindings.
 Test Lab DB-backed no-send.
 Publish Control no-send.
 Frontend de Agent Builder.

Pero la auditoría también encontró problemas graves

 WhatsAppBaileys live todavía entra por `ConversationRunner`.
 `ConversationRunner` sigue siendo puente operativo real.
 Runtime V2 se engancha desde el runner si la config lo permite.
 El live no es Product-First limpio de punta a punta.
 El composer actual sigue basado en `ValidatedResponsePlan`, `pending_slot`, `next_best_question` y reparaciones.
 Hay legacy cerca de la ruta visible.
 El worktree está muy sucio.
 No se debe confundir Test Labno-send con live readiness.

Después de esa auditoría se inició una nueva ruta Respond-Style, sin live y sin tocar WhatsApp.

Fases implementadas hasta ahora

Fase 1 — Customer Copy Kill Map

Estado
`CUSTOMER_COPY_SOURCES_MAPPED`

Archivo
`docsarchitecturecustomer_copy_kill_map.md`

Objetivo
Mapear todas las fuentes que pueden escribir texto visible al cliente.

Incluye

 ConversationRunner
 response_contract
 composer_prompts
 StructuredRuntimeComposer
 HumanResponseComposer
 ValidatedResponsePlanBuilder
 fallbacks
 guards
 workflow copy
 handoff copy
 providermanual fallback
 SendAdapter
 outbox

Clasificaciones usadas

 KEEP_INTERNAL_ONLY
 BLOCK_FOR_PRODUCT_AGENT
 DEGRADE_TO_LEGACY_ONLY
 REPLACE_WITH_LLM_TURN
 DELETE_LATER

Fase 2 — Respond-Style Turn Contract

Estado
`RESPOND_STYLE_TURN_CONTRACT_READY`

Archivo
`coreatendiaagent_runtimerespond_style_turn_contract.py`

Define schemas puros

 AgentTurnInput
 AgentContextPackage
 LLMToolCallProposal
 LLMFieldUpdateProposal
 LLMWorkflowEventProposal
 LLMHandoffProposal
 LLMClaim
 LLMAgentTurnOutput
 ValidationErrorItem
 AgentTurnValidationResult
 AgentTurnRetryInstruction
 FinalTurnDecision

Intención
El LLM produce respuesta + propuestas.
AtendIA validaejecutaaudita.

Fase 3 — Respond-Style Turn Validator

Estado
`RESPOND_STYLE_TURN_VALIDATOR_READY`

Archivo
`coreatendiaagent_runtimerespond_style_turn_validator.py`

Valida

 final_message requerido
 internal leaks
 claims con soporte
 precio solo con quote.resolve
 requisitos solo con requirements.lookup
 field writes con policyevidencia
 workflow bindings
 actions permitidas
 handoff válido
 retry instruction si el error es reparable
 no_send si no es seguro

Fase 4 — Respond-Style LLM Turn Provider no-live

Estado
`RESPOND_STYLE_LLM_TURN_PROVIDER_READY`

Archivo
`coreatendiaagent_runtimerespond_style_llm_provider.py`

Hace

 recibe AgentTurnInput + AgentContextPackage
 construye prompt desde configcontextcapabilities
 llama OpenAI-compatible client con JSON schema estricto
 parsea LLMAgentTurnOutput
 valida con RespondStyleTurnValidator
 permite máximo 1 retry con feedback estructurado
 fuerza siempre no_send
 no toca AgentService
 no toca SendAdapter
 no toca outbox
 no toca workflowsactions reales
 no usa ConversationRunner
 no usa HumanResponseComposer
 no usa StructuredRuntimeComposer

Fase 4B — OpenAI real no-send provider verification

Estado
`PHASE_4B_OPENAI_REAL_NO_SEND_PROVIDER_PASSED`

El runner fue actualizado para leer key desde

 OPENAI_API_KEY
 ATENDIA_V2_OPENAI_API_KEY
 fallback en core.env

La corrida real no-send pasó.

Observación
El modelo fue conservador y no siempre propuso tool en casos genéricos como “qué ocupo”. Eso motivó Fase 5.

Fase 5 — Respond-Style Tool Loop no-send

Estado
`PHASE_5_RESPOND_STYLE_TOOL_LOOP_NO_SEND_READY`

Archivo
`coreatendiaagent_runtimerespond_style_tool_loop.py`

Hace

 llama provider turn 1
 toma tool proposals validadas
 ejecuta RespondStyleToolExecutor inyectado en dryfact-only
 reinserta tool_results en AgentContextPackage
 llama provider turn 2
 valida
 falla cerrado si tool requerida fallase saltano está bound
 fuerza siempre no_send
 no outbox
 no workflowsactions reales
 no SendAdapter
 no AgentService
 no legacy composer

Resultado real

 requirements.lookup fue propuesta y ejecutada con preconditions completas.
 el segundo LLM redactó desde facts.
 cuando faltó precondition de precio, falló cerrado con no_send, sin copy visible.

Fase 6 — Respond-Style Shadow Runner no-send

Estado
`PHASE_6_RESPOND_STYLE_SHADOW_RUNNER_READY`

Archivo
`coreatendiaagent_runtimerespond_style_shadow_runner.py`

Hace

 compara una ruta actual inyectadasnapshot contra RespondStyleToolLoop
 produce ShadowRunResult auditable
 fuerza no_send
 registra toolstool_resultsvalidator decisions
 calcula scores simples de copy quality
 no importa ConversationRunner
 no importa HumanResponseComposer
 no importa StructuredRuntimeComposer
 no importa SendAdapter
 no outbox
 no enqueue_messages
 no evaluate_event
 no hardcodes DinamomotoscréditoSATMetrotranscript

Resultado

 tests pasaron
 runner OpenAI real no-send pasó
 un escenario de modelo falló cerrado con no_send, lo cual es correcto para shadow
 eso señaló un gap de contextotool intent antes de ruta directa

Siguiente fase propuesta

Fase 7 — Respond-Style Context Package Builder

Objetivo
Crear `RespondStyleContextPackageBuilder`.

Debe construir `AgentTurnInput` y `AgentContextPackage` desde

 Product Agent config
 promptpersonainstrucciones
 recent transcript
 contact state
 known fields
 missing fields
 KB snippets
 tool schemas
 tool preconditions
 action schemas
 workflow trigger schemas
 field schemas
 hard policies
 current stagepipeline
 handoff options
 no-sendlive mode

Principio
El builder NO conversa.
El builder NO decide frases.
El builder NO fuerza tools por keyword.
El builder NO repara mensajes.
El builder solo prepara contexto estructurado.

Después de Fase 7, se planea

Fase 8 — ProductAgentRuntime direct path no-send
Fase 9 — Test Lab same route as future live
Fase 10 — AgentService integration no-send
Fase 11 — ConversationRunner bypass for Product Agents
Fase 12 — legacy customer-copy hard block
Fase 13 — controlled smoke

Archivos que voy a darte

Te voy a compartir, como mínimo

1. `AUDITORIA_COMPLETA_ATENDIA_2026_06_09.md`
2. `Arquitectura-Deseada.md`
3. `PRODUCT_FIRST_LIVE_STABLE_CODEX_IMPLEMENTATION.md`
4. `respond_style_runtime_implementation_plan.md`
5. `docsarchitecturecustomer_copy_kill_map.md`
6. `coreatendiaagent_runtimerespond_style_turn_contract.py`
7. `coreatendiaagent_runtimerespond_style_turn_validator.py`
8. `coreatendiaagent_runtimerespond_style_llm_provider.py`
9. `coreatendiaagent_runtimerespond_style_tool_loop.py`
10. `coreatendiaagent_runtimerespond_style_shadow_runner.py`
11. tests de esas fases
12. reports de Fase 1 a Fase 6
13. transcripts reales fallidos de WhatsApp
14. reportes de smokes fallidos

Tu tarea

# 1. Veredicto brutal actualizado

Dime si AtendIA está realmente avanzando hacia Product-First Live Estable o si sigue siendo un bot legacy con piezas nuevas encima.

No confundas

 archivo existe con integración real
 no-send con live
 shadow con producción
 validator con conversación humana
 tool loop fakedry con tool loop live

# 2. Evalúa la ruta Respond-Style Fase 1 a Fase 6

Revisa críticamente

 customer_copy_kill_map.md
 respond_style_turn_contract.py
 respond_style_turn_validator.py
 respond_style_llm_provider.py
 respond_style_tool_loop.py
 respond_style_shadow_runner.py

Preguntas

 ¿Esta arquitectura realmente saca la conversación visible de AtendIA
 ¿El LLM es quien conversa
 ¿AtendIA solo validaorquesta
 ¿Siguen existiendo ifs conversacionales
 ¿Hay hidden composer disfrazado
 ¿El validator está validando facts o está empezando a escribir conversación
 ¿El tool loop es correcto
 ¿El shadow runner sirve o da falsa confianza
 ¿Qué falta antes de conectar a AgentService

# 3. Legacy customer-facing

Identifica toda pieza que todavía pueda escribir texto visible al cliente

 ConversationRunner
 HumanResponseComposer
 StructuredRuntimeComposer
 ValidatedResponsePlanBuilder
 fallbacks
 repairs
 guards que reescriben
 workflow copy
 handoff copy
 provider fallback
 manual fallback
 SendAdapteroutbox path
 cualquier bridge legacy

Para cada una, dime

 archivo
 si participa en live
 si puede escribir customer copy
 si debe morir, congelarse o migrarse
 riesgo
 qué gate debe bloquearla

# 4. Evalúa Fase 7 antes de implementarla

Quiero saber si la siguiente fase correcta es realmente

`RespondStyleContextPackageBuilder`

Evalúa

 qué debe incluir
 qué NO debe incluir
 qué sería hardcode disfrazado
 cómo exponer tools sin forzar tools por keyword
 cómo exponer fields sin guiar conversación como formulario
 cómo exponer workflows sin side effects
 cómo empaquetar KB sin permitir facts inventados
 cómo asegurar que el LLM tenga suficiente contexto para no fallar cerrado innecesariamente
 cómo asegurar que no genere customer copy el builder

# 5. Qué matar  congelar  mantener

Clasifica componentes en

 KEEP
 KEEP_INTERNAL_ONLY
 SHADOW_ONLY
 FREEZE_LEGACY
 REPLACE
 DELETE_LATER
 DELETE_NOW_IF_SAFE

Incluye especialmente

 ConversationRunner
 HumanResponseComposer
 StructuredRuntimeComposer
 ValidatedResponsePlanBuilder
 PolicyValidator viejo
 RespondStyleTurnValidator
 RespondStyleLLMTurnProvider
 RespondStyleToolLoop
 RespondStyleShadowRunner
 SendAdapter
 Outbox
 Workflow engine
 Product Agent Builder
 Test Lab
 Publish Control

# 6. Input  Processing  Output final ideal

Descríbeme con lujo de detalle la arquitectura correcta para Product-First Live Estable.

Input

 WhatsAppBaileysMeta message
 recent transcript
 contact state
 agent config
 KB bindings
 tool schemas
 action schemas
 workflow schemas
 field schemas
 publish state
 send scope
 no-sendlive mode

Processing

 channel adapter
 inbox persistence
 deployment resolver
 ProductAgentRuntime direct path
 RespondStyleContextPackageBuilder
 LLM agent turn
 tool loop
 validation
 retry with feedback
 field write proposal validation
 workflow proposal validation
 handoff proposal
 send policy
 trace
 outbox staging if allowed

Output

 final_message
 field updates
 workflow events
 handoff
 no-sendlive decision
 audit trace
 outbox only through SendAdapter

# 7. Gaps antes de live

Dime qué falta antes de conectar a live.

Especialmente

 ProductAgentRuntime direct path
 AgentService integration no-send
 Test Lab same route as live
 ConversationRunner bypass
 legacy customer-copy hard block
 field persistence
 workflowaction dry-run
 action permissions
 real KB retrieval
 real tools
 tool result citations
 retry loop reliability
 observability
 rollback
 worktree baseline

# 8. Pruebas obligatorias antes de otro smoke

Dime exactamente qué tests y simulations deben pasar antes de otro smoke

 replay de transcripts fallidos
 Dinamo scenarios
 multi-tenant scenarios
 tool loop
 field write
 workflow triggers
 handoff
 no internal leaks
 no unsupported claims
 no legacy route
 same Test Lablive path
 sourcecontainer parity
 OpenAI real no-send
 shadow comparison
 ProductAgentRuntime direct path no-send
 rollback packet

# 9. Plan de migración sin temporales eternos

Dame un plan por fases para llegar a Product-First Live Estable.

Incluye

 qué se puede implementar ya
 qué debe esperar
 qué gate desbloquea cada fase
 qué se elimina después
 cuándo se puede matar ConversationRunner para Product Agents
 cuándo se puede bloquear HumanResponseComposer para Product Agents
 cuándo se puede volver a WhatsApp
 cuándo se puede permitir workflowsactions reales

# 10. Riesgos

Haz matriz de riesgos

 riesgo
 severidad
 evidencia
 impacto
 fix correcto
 qué NO hacer

# 11. Decisión final

Usa una sola

 READY_TO_BUILD_PHASE_7_CONTEXT_PACKAGE_BUILDER
 BLOCKED_BY_PHASE_1_6_DESIGN_FLAW
 BLOCKED_BY_LEGACY_LIVE_PATH
 BLOCKED_BY_MISSING_PRODUCT_AGENT_RUNTIME_DIRECT_PATH
 BLOCKED_BY_MISSING_CONTEXT_PACKAGE
 BLOCKED_BY_DIRTY_WORKTREE
 UNSAFE_TO_CONNECT_TO_LIVE

Reglas

 No me des motivación.
 No me vendas humo.
 No propongas más composer encima del composer.
 No propongas fixes por frase.
 No digas que está listo si sigue pasando por ConversationRunner.
 No confundas no-send con live.
 No confundas shadow con producción.
 No confundas archivo existente con integración real.
 No aceptes blocked phrase lists como estrategia de calidad.
 No dejes que validators se conviertan en guionistas.
 No aceptes workflow customer-copy.
 Sé brutalmente claro.
 Dame recomendaciones accionables.
