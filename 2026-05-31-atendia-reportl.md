# AtendIA v2 vs respond.io — revisión mejorada y recomendaciones

Fecha: 2026-05-31
Base: reporte original `atendia-vs-respondio-2026-05-31.md` generado por Codex y revisado de nuevo.
Alcance: estrategia de producto, madurez operativa, arquitectura de IA, roadmap y recomendaciones comerciales.
Nota: no se verificó información pública nueva de respond.io en web dentro de esta revisión. Las referencias públicas, precios y capacidades de respond.io se toman como base del reporte original y deben revalidarse antes de usar el documento para una decisión comercial formal.

---

## 1. Veredicto ejecutivo mejorado

El reporte original está bien orientado: no trata a AtendIA como una copia menor de respond.io, sino como una apuesta diferente. Esa lectura es correcta.

La comparación más útil no es:

```text
AtendIA vs respond.io: ¿quién tiene más features?
```

La comparación correcta es:

```text
respond.io = plataforma horizontal madura para conversaciones omnicanal.
AtendIA = sistema vertical de decisiones comerciales por WhatsApp con IA, cotización, documentos, pipeline y handoff.
```

La recomendación central es:

> AtendIA no debe intentar igualar a respond.io en amplitud. Debe acercarse a su madurez operativa, pero ganar por profundidad vertical.

En términos prácticos:

* respond.io gana si el cliente necesita muchos canales, integraciones listas, mobile app, broadcasts, reportes ejecutivos y seguridad enterprise desde el día uno.
* AtendIA puede ganar si el cliente necesita vender mejor por WhatsApp, cotizar sin inventar, pedir documentos en orden, dar seguimiento, escalar a humano y auditar por qué la IA respondió algo.
* La pelea no debe ser “somos otro inbox omnicanal”. La pelea debe ser “somos el asesor comercial IA que convierte conversaciones complejas de WhatsApp en ventas medibles”.

La prioridad de AtendIA no debería ser construir más pantallas ni más canales. La prioridad debería ser que el agente sea confiable, natural, trazable y conectado a datos reales.

### Brújula de enfoque

AtendIA no debería perseguir todo eso todavía. Debe ganar primero en:

* WhatsApp-first;
* ventas complejas;
* cotización segura;
* documentos por plan;
* expediente inteligente;
* handoff humano;
* IA auditable;
* trazabilidad por respuesta.

La brújula de producto queda así:

> AtendIA no debe ganar por tener más features. Debe ganar porque en el canal más importante del cliente, la IA vende mejor, se equivoca menos, explica más y deja menos dinero perdido.

---

## 2. Lo que sí está bien del reporte original

El reporte original acierta en cuatro puntos importantes.

### 2.1. El posicionamiento es correcto

El reporte entiende que respond.io es una plataforma SaaS horizontal y que AtendIA tiene una lógica más vertical: ventas por WhatsApp, IA operativa, catálogo, requisitos, documentos, pipeline y trazas.

Eso es clave, porque si AtendIA se vende como “respond.io hecho en casa”, pierde. Si se vende como “respond.io vertical para ventas complejas por WhatsApp”, tiene una narrativa mucho más fuerte.

### 2.2. Detecta bien los gaps grandes

Los gaps reales frente a respond.io son claros:

* omnicanalidad;
* mobile app;
* broadcasts/campañas;
* integraciones comerciales;
* reportes ejecutivos;
* workflows visuales maduros;
* seguridad enterprise;
* producto empaquetado y soporte SaaS.

Estos gaps importan, pero no todos importan al mismo tiempo. La mejora principal del reporte debe ser priorizarlos.

### 2.3. Identifica bien el mayor riesgo técnico

El reporte menciona que AtendIA tiene demasiadas capas capaces de influir en la decisión o en el texto final: `conversation_runner`, `advisor_brain`, `sales_advisor_decision_policy`, `turn_resolver`, `response_frame`, `response_contract`, `composer` y `agent_final_response`.

Ese punto debería estar todavía más arriba. Es el riesgo P0.

Cuando muchas capas pueden decidir o redactar, aparecen síntomas como:

* preguntas repetidas;
* respuestas robóticas;
* mensajes duplicados;
* campos contaminados;
* etapas movidas sin evidencia;
* cotizaciones incorrectas;
* documentos pedidos antes de tiempo;
* handoff tardío o innecesario;
* dificultad para explicar por qué el bot dijo algo.

### 2.4. La recomendación de no copiar todo respond.io es correcta

El reporte dice que no conviene copiar omnicanalidad completa, workflows infinitos ni cotización como knowledge source genérica. Esa recomendación es muy importante.

AtendIA debe copiar patrones de madurez, no la amplitud completa del producto.

---

## 3. Lo que le falta al reporte original

El reporte original es bueno como auditoría comparativa, pero le faltan capas de decisión. Para que sea útil como documento de ejecución, agregaría estas secciones.

### 3.1. Separar “lo vendible” de “lo técnico”

AtendIA puede tener muchas piezas técnicas impresionantes, pero el comprador no compra arquitectura. Compra resultados.

El comprador quiere:

```text
Más leads atendidos.
Menos leads perdidos.
Cotizaciones correctas.
Seguimiento automático.
Documentos completos.
Menos errores del asesor.
Más citas y cierres.
Visibilidad para el gerente.
```

Por eso el reporte debería separar:

| Tipo                    | Ejemplo                                                | Cómo se vende                                  |
| ----------------------- | ------------------------------------------------------ | ---------------------------------------------- |
| Valor comercial directo | Cotización, seguimiento, documentos, handoff           | “Te ayuda a vender más y perder menos leads”   |
| Operación diaria        | Inbox, pipeline, vistas guardadas, notas, asignaciones | “Tu equipo sabe qué atender y cuándo”          |
| Confianza IA            | trazas, evidencia, guardrails, replay                  | “La IA no inventa y puedes auditarla”          |
| Infraestructura interna | workers, outbox, state gateway, NLU router             | No se vende como feature; sostiene el producto |
| Enterprise              | SSO, audit log, retention, backups                     | Se vende solo cuando el cliente lo exige       |

### 3.2. Falta una matriz de “bloquea producción vs puede esperar”

El reporte lista muchos gaps, pero no distingue cuáles bloquean salir a producción.

La separación correcta sería:

| Nivel                           | Elementos                                                                                                                               |
| ------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| Bloquea producción              | autoridad final única, escritura de estado controlada, WhatsApp estable, dedupe, outbox, handoff, cotización sin inventar, logs mínimos |
| Necesario para operación diaria | inbox usable, vistas guardadas, pipeline, documentos, búsqueda, reportes básicos, followups                                             |
| Diferenciador                   | why-this-answer, replay, KB health, quote confidence, expediente inteligente                                                            |
| Puede esperar                   | omnicanalidad amplia, mobile nativo, integraciones enterprise, workflow canvas avanzado, certificaciones                                |

### 3.3. Falta definir el comprador ideal

Sin ICP claro, el roadmap se vuelve infinito.

AtendIA debería priorizar un comprador como:

```text
Negocio donde WhatsApp es el canal principal de venta,
la venta requiere explicación,
el precio depende de catálogo/plan,
el cliente debe mandar documentos,
y un gerente necesita saber en qué etapa está cada lead.
```

Ejemplos:

* agencias de motos;
* financiamiento/credito automotriz;
* inmobiliarias con precalificación;
* escuelas/cursos con admisión;
* clínicas con requisitos previos;
* servicios donde se cotiza y se da seguimiento.

Para el caso actual, la narrativa más fuerte sigue siendo motos/crédito/WhatsApp.

### 3.4. Falta definir una “versión vendible mínima”

No todo lo que tiene respond.io es necesario para vender AtendIA.

Una versión vendible mínima debería incluir:

```text
WhatsApp conectado
Inbox básico
Pipeline comercial
Catálogo/cotización confiable
Requisitos/documentos por plan
Agente IA con guardrails
Handoff humano
Followups básicos
Dashboard de leads y etapas
Debug/evidencia por respuesta
```

Eso sería más valioso para un nicho que tener 12 canales sin profundidad.

### 3.5. Falta convertir las recomendaciones en tickets accionables

El reporte tiene un backlog, pero aún está demasiado general. Conviene convertirlo a épicas con criterios de aceptación.

Ejemplo:

```text
Épica: Autoridad final única de respuesta
Aceptación:
- Ningún tool devuelve texto final visible.
- Solo AgentFinalResponse puede emitir mensaje final.
- Cada turno guarda final_response_id.
- Cada mensaje visible tiene trace_id.
- Canaries fallan si hay dos mensajes del bot para el mismo turno.
```

---

## 4. Posicionamiento recomendado

### 4.1. Posicionamiento corto

> AtendIA es un asesor comercial IA para WhatsApp que cotiza, precalifica, pide documentos, da seguimiento, escala a humanos y explica cada decisión.

### 4.2. Posicionamiento frente a respond.io

> respond.io organiza conversaciones omnicanal. AtendIA convierte conversaciones complejas de WhatsApp en ventas auditables.

### 4.3. Posicionamiento para agencia de motos/crédito

> AtendIA atiende leads por WhatsApp como un asesor experto: entiende qué moto quiere el cliente, valida plan y enganche, cotiza con catálogo real, responde dudas de crédito, solicita documentos correctos y avisa al humano cuando debe intervenir.

### 4.4. Lo que no conviene decir

Evitar:

```text
Somos como respond.io pero más barato.
Somos un CRM omnicanal completo.
Tenemos todo lo que tiene respond.io.
Nuestro bot puede hacer cualquier cosa.
```

Mejor decir:

```text
Somos especialistas en ventas por WhatsApp con IA y control comercial.
```

---

## 5. Relectura de la comparación

### 5.1. Donde respond.io gana claramente

respond.io gana en amplitud y madurez:

* canales;
* inboxes maduras;
* workflows visuales;
* broadcasts;
* integraciones;
* mobile;
* reportes ejecutivos;
* seguridad/certificaciones;
* producto empaquetado;
* time-to-value generalista.

Esto importa cuando el cliente quiere “comprar y operar” sin desarrollar nada.

### 5.2. Donde AtendIA puede ganar

AtendIA puede ganar en profundidad:

* cotización determinística;
* catálogo como fuente de verdad;
* documentos por plan;
* estados `DOCS_*`;
* Vision para expediente;
* trazas de decisión;
* handoff con razón y riesgo;
* agente más natural si se consolida la arquitectura;
* self-host/control de datos;
* lógica vertical ajustada al negocio.

### 5.3. Donde el reporte original es un poco optimista

El reporte da a AtendIA una calificación alta en IA vertical. Conceptualmente tiene sentido, pero conviene separar:

| Dimensión                     | Lectura honesta                             |
| ----------------------------- | ------------------------------------------- |
| Potencial de IA vertical      | Alto                                        |
| Arquitectura base             | Fuerte pero compleja                        |
| Producto IA terminado         | Todavía en consolidación                    |
| Confianza operacional         | Depende de resolver P0                      |
| Ventaja comercial demostrable | Debe probarse con métricas de cierres/leads |

No basta con tener herramientas y trazas. El criterio real es:

```text
¿El agente responde bien 100 conversaciones reales seguidas sin inventar, repetir ni trabarse?
```

### 5.4. Donde el reporte original es un poco suave

El reporte debería ser más duro en estos puntos:

1. **Pricing/packaging**: sin paquete vendible, la tecnología no se convierte en producto.
2. **Onboarding**: si configurar un tenant requiere developer, respond.io gana por default.
3. **Reportes de negocio**: un gerente no quiere traces; quiere saber ventas, leads, etapas, pérdidas y asesores.
4. **Catálogo y datos**: si el catálogo está desactualizado, la IA confiable se vuelve peligrosa.
5. **Mantenimiento del conocimiento**: FAQ, requisitos, promociones y políticas deben tener dueño, versión y fecha de vigencia.

---

## 6. Recomendaciones P0: confianza operacional

Esta fase debe ir antes de copiar más features de respond.io.

### 6.1. Una sola autoridad de respuesta final

Recomendación:

```text
Solo AgentFinalResponse puede producir el mensaje visible final.
```

Las demás capas deben tener roles claros:

| Capa               | Rol recomendado               | Lo que no debe hacer               |
| ------------------ | ----------------------------- | ---------------------------------- |
| NLU                | extraer intención y entidades | redactar respuesta final           |
| Runner             | decidir siguiente acción      | escribir copy final largo          |
| Tools              | devolver facts/evidencia      | inventar mensaje comercial final   |
| StateWriteGateway  | validar y escribir estado     | decidir conversación completa      |
| Composer           | redactar candidato            | escribir sin evidencia ni estado   |
| OutboundGuard      | aprobar/bloquear salida       | cambiar lógica comercial sin trace |
| AgentFinalResponse | mensaje final único           | saltarse guardrails                |

Criterios de aceptación:

* cada turno tiene exactamente un `final_response`;
* cada mensaje visible tiene `trace_id`;
* ningún tool devuelve copy final listo para enviar salvo plantillas explícitas;
* si un flujo intenta emitir dos respuestas, el guard bloquea;
* los tests fallan si hay mensajes duplicados en un turno.

### 6.2. StateWriteGateway obligatorio

Recomendación:

```text
Ninguna capa debe escribir directamente campos comerciales sensibles.
```

Campos sensibles:

* moto/modelo;
* plan/crédito;
* enganche;
* plazo;
* pago mensual;
* etapa del pipeline;
* documentos recibidos;
* estatus de buró;
* cita;
* asesor asignado.

Cada escritura debe guardar:

```json
{
  "field": "MOTO",
  "old_value": null,
  "new_value": "Adventure 250",
  "source": "customer_message | tool | human | vision | workflow",
  "evidence": "mensaje_id o documento_id",
  "confidence": 0.92,
  "approved_by": "state_write_policy",
  "trace_id": "..."
}
```

Criterios de aceptación:

* no hay escrituras sin evidencia;
* se puede revertir un cambio;
* el panel del contacto muestra de dónde salió cada dato;
* cambios de etapa requieren razón;
* Vision no marca documentos como válidos sin confianza mínima o revisión humana según regla.

### 6.3. Canaries conversacionales obligatorios

Antes de agregar features, AtendIA necesita pruebas de conversaciones reales.

Casos mínimos:

1. Cliente pregunta precio de modelo específico.
2. Cliente no sabe qué modelo quiere.
3. Cliente trae buró.
4. Cliente quiere crédito pero no tiene comprobantes.
5. Cliente manda INE.
6. Cliente manda documento borroso.
7. Cliente pregunta algo fuera de tema.
8. Cliente pide humano.
9. Cliente contradice un dato anterior.
10. Cliente responde con “sí”, “esa”, “la roja”, “20%”, “por fuera”.

Reglas de aprobación:

* responde primero la pregunta actual;
* no inventa precio;
* no cotiza sin modelo/plan cuando son requeridos;
* no repite pregunta si ya tiene el dato;
* pregunta máximo una cosa crítica a la vez;
* no pide documentos antes de resolver intención principal, salvo que el flujo lo justifique;
* escala si hay baja confianza o conflicto.

### 6.4. Ingesta y salida robustas

Checklist mínimo:

* dedupe de webhooks;
* idempotencia en inbound;
* outbox transaccional;
* retry con backoff;
* status enviado/entregado/leído/fallido;
* manejo de ventana 24h de WhatsApp;
* templates aprobados para recontacto;
* pausa por humano;
* reanudación segura del bot;
* log de errores visible para admin técnico.

Sin esto, cualquier comparación con respond.io queda débil porque la operación diaria se rompe.

---

## 7. Recomendaciones P1: producto vendible mínimo

### 7.1. Onboarding guiado por tenant

AtendIA necesita un onboarding que reduzca dependencia técnica.

Flujo recomendado:

```text
1. Crear tenant
2. Conectar WhatsApp
3. Cargar catálogo
4. Cargar requisitos por plan
5. Cargar FAQ/políticas
6. Configurar pipeline
7. Configurar agente
8. Probar conversaciones simuladas
9. Publicar
10. Ver dashboard inicial
```

Criterios de aceptación:

* un tenant admin puede completar onboarding sin editar código;
* el sistema valida catálogo incompleto;
* el sistema detecta planes sin requisitos;
* el sistema muestra una conversación de prueba antes de publicar;
* hay rollback de agente/configuración.

### 7.2. Inbox con vistas guardadas

No necesitas copiar todo respond.io, pero sí necesitas operación diaria clara.

Vistas mínimas:

* Míos;
* Sin asignar;
* Urgentes;
* Handoff pendiente;
* Cotización enviada;
* Documentos pendientes;
* Documentos recibidos;
* Sin respuesta del cliente;
* Sin respuesta del asesor;
* Alto valor;
* Por etapa;
* Por agente IA.

Cada vista debería permitir:

* guardar filtros;
* compartir con equipo;
* ordenar por prioridad/SLA/último mensaje;
* asignar conversación;
* pausar/reanudar bot;
* mover etapa;
* ver razón de IA.

### 7.3. Dashboard gerencial mínimo

El dashboard inicial debe contestar preguntas de gerente, no de developer.

Métricas mínimas:

| Métrica                    | Pregunta que responde             |
| -------------------------- | --------------------------------- |
| Leads nuevos               | ¿Cuántas oportunidades entraron?  |
| Leads atendidos por IA     | ¿Cuánto trabajo absorbió AtendIA? |
| Tiempo a primera respuesta | ¿Estamos respondiendo rápido?     |
| Cotizaciones enviadas      | ¿Cuántos leads llegaron a precio? |
| Conversión por etapa       | ¿Dónde se están atorando?         |
| Documentos completos       | ¿Cuántos expedientes avanzan?     |
| Handoffs                   | ¿Dónde necesita humano?           |
| Pérdidas/motivos           | ¿Por qué no cierran?              |
| Valor potencial            | ¿Cuánto dinero hay en pipeline?   |
| Errores/baja confianza IA  | ¿Dónde hay que corregir?          |

### 7.4. Cotización como módulo estrella

La cotización debe sentirse como el corazón del producto.

Recomendaciones:

* alias de modelos;
* validación de disponibilidad;
* vigencia de precio;
* plan/enganche/plazo;
* promociones;
* explicación breve para cliente;
* snapshot de cotización;
* historial por lead;
* alerta si catálogo cambió;
* “quote confidence”;
* trazabilidad de cada número.

Regla fundamental:

```text
El LLM nunca inventa precio, enganche, mensualidad ni requisito.
```

### 7.5. Documentos como expediente, no como adjuntos

La ventaja de AtendIA no es “recibir archivos”. Es convertir documentos en estado comercial.

Estados recomendados:

```text
No solicitado
Solicitado
Recibido
En revisión
Aceptado
Rechazado
Vencido
Borroso/Incompleto
Requiere humano
```

Cada documento debe tener:

* tipo;
* plan asociado;
* archivo original;
* resultado Vision;
* confianza;
* observación;
* quién lo validó;
* fecha;
* impacto en pipeline.

### 7.6. Followups básicos antes que broadcasts complejos

No conviene construir campañas masivas completas todavía. Primero followups transaccionales.

Casos prioritarios:

* cotización enviada sin respuesta;
* documentos pendientes;
* cita pendiente de confirmar;
* lead frío con intención alta;
* cliente pidió volver después;
* humano no respondió;
* documento rechazado.

Requisitos:

* opt-out;
* frecuencia máxima;
* ventana 24h o template;
* trazabilidad;
* pausa si humano toma conversación;
* no enviar followup si el cliente ya respondió.

---

## 8. Recomendaciones P2: diferenciadores reales

### 8.1. “¿Por qué dijo esto la IA?”

Esta podría ser una de las mejores features de AtendIA.

Desde cada burbuja del bot, mostrar:

* intención detectada;
* datos extraídos;
* tools usados;
* catálogo/FAQ/documento consultado;
* cambios de estado;
* confianza;
* reglas aplicadas;
* razón de handoff si aplica;
* mensaje final aprobado.

Esto no debería ser una pantalla solo para developers. Debe servir a un admin o gerente.

### 8.2. KB Command Center real

El reporte original menciona que algunas superficies de KB parecen mock/parciales. Ahí hay una oportunidad enorme.

Módulos recomendados:

| Módulo                     | Valor                                                   |
| -------------------------- | ------------------------------------------------------- |
| Preguntas sin respuesta    | Detecta qué FAQ falta                                   |
| Conflictos de conocimiento | Evita que dos documentos digan precios/reglas distintas |
| Vigencia de promociones    | Evita vender promociones vencidas                       |
| Knowledge tests            | Prueba respuestas antes de publicar                     |
| Impacto por fuente         | Mide qué documentos ayudan o dañan                      |
| Riesgo por respuesta       | Detecta temas donde la IA baja confianza                |

### 8.3. Replay/A-B de agentes

Diferenciador fuerte:

```text
Tomar conversaciones reales pasadas y probar cómo respondería una nueva versión del agente sin afectar clientes.
```

Esto permite:

* publicar prompts con menos riesgo;
* comparar agente actual vs agente nuevo;
* medir repetición, invención, handoff, cotización;
* detectar regresiones;
* entrenar mejores políticas.

### 8.4. Handoff learning loop

Cada handoff debería generar aprendizaje.

Cuando humano toma una conversación, registrar:

* por qué se escaló;
* si la escalación fue correcta;
* qué respondió el humano;
* qué debería aprender la IA;
* si falta FAQ/regla/tool;
* si fue problema de conocimiento, tono, riesgo o negocio.

Esto convierte el handoff en dataset de mejora.

### 8.5. Money dashboard

Para vender AtendIA, el dashboard debe hablar dinero.

Métricas:

* valor potencial de pipeline;
* valor cotizado;
* cotizaciones por modelo;
* etapa donde se pierde más dinero;
* asesor/agente con mejor avance;
* leads de alto valor sin atender;
* documentos que bloquean cierres;
* motivos de pérdida;
* tiempo desde lead a cotización;
* tiempo desde cotización a documentos;
* tiempo desde documentos a cita/cierre.

---

## 9. Recomendaciones P3: madurez comercial/enterprise

Estas no deben ir antes de resolver P0/P1.

### 9.1. Seguridad mínima vendible

Antes de vender a clientes más formales:

* 2FA;
* permisos por rol y acción;
* audit log exportable;
* data export;
* retention policies;
* backups documentados;
* secret rotation;
* sesiones y dispositivos;
* masking de teléfono/correo si aplica;
* política de acceso a documentos.

SSO y certificaciones pueden esperar hasta que haya clientes que lo exijan.

### 9.2. Integraciones priorizadas

No construir todas. Prioridad recomendada:

1. Webhooks salientes robustos.
2. API pública básica.
3. Zapier/Make/n8n.
4. Google Sheets/CSV import-export bien hecho.
5. HubSpot.
6. Salesforce.
7. Meta Ads/product catalog si el nicho lo necesita.

### 9.3. Mobile/PWA

No empezaría con app nativa. Primero PWA fuerte.

Casos móviles:

* asesor recibe notificación;
* toma conversación;
* responde rápido;
* ve datos del lead;
* pausa/reanuda bot;
* revisa documentos;
* marca seguimiento.

### 9.4. Omnicanalidad gradual

Orden recomendado:

1. WhatsApp perfecto.
2. Instagram DM si el nicho lo usa mucho.
3. Facebook Messenger si hay ads/leads ahí.
4. Webchat si hay tráfico web.
5. Email como soporte administrativo.
6. Otros canales solo con demanda real.

No competir contra respond.io en omnicanalidad completa todavía.

---

## 10. Roadmap mejorado

### Fase 0 — Confiabilidad del cerebro

Objetivo: que el agente no invente, no repita, no escriba mal estado y sea auditable.

Prioridades:

* autoridad final única;
* state write gateway;
* tools facts-only;
* outbound guard;
* canaries multiturn;
* trace obligatorio;
* manejo de errores visible;
* pausa/reanudación segura.

Resultado esperado:

```text
100 conversaciones de prueba pasan sin respuestas duplicadas,
sin cotizaciones inventadas,
sin escritura de estado sin evidencia,
y con trace completo por turno.
```

Estado de implementacion al 2026-05-31:

* `AgentFinalResponse` quedo como frontera final mediante `finalize_agent_visible_response`.
* El runner aplica esa frontera antes del trace/outbox y tambien despues de reescrituras tardias.
* Los tools comerciales se normalizan como facts-only y no deben transportar copy final visible.
* `StateWritePolicy` bloquea documentos marcados desde texto y agrega evidencia/fuente a escrituras aprobadas.
* Los canaries cubren preguntas actuales, cotizacion, documentos, aprobacion, handoff, contradicciones y respuestas cortas.
* Verificacion local: `tests/architecture/test_multiturn_runner_flows.py` con 142 casos y el paquete enfocado de 62 contratos pasan.

### Fase 1 — Operación diaria vendible

Objetivo: que un equipo use AtendIA todos los días.

Prioridades:

* inbox con vistas guardadas;
* pipeline operativo;
* contacto con campos comerciales;
* documentos por plan;
* handoff claro;
* followups básicos;
* búsqueda global;
* dashboard de leads/etapas;
* onboarding tenant.

Resultado esperado:

```text
Un negocio puede conectar WhatsApp, cargar catálogo/requisitos,
probar el agente y operar leads reales desde inbox/pipeline.
```

### Fase 2 — Diferenciación frente a respond.io

Objetivo: que AtendIA haga cosas que respond.io no hace igual de profundo.

Prioridades:

* quote confidence;
* expediente inteligente;
* why-this-answer;
* KB Command Center real;
* replay/A-B de agentes;
* handoff learning loop;
* money dashboard.

Resultado esperado:

```text
AtendIA no solo responde; demuestra por qué respondió,
qué datos usó, cuánto dinero hay en juego y qué debe mejorar.
```

### Fase 3 — Escala comercial

Objetivo: vender y operar con menos fricción.

Nota de alcance: esta fase no debe abrir la puerta a perseguir amplitud horizontal antes de tiempo. PWA, integraciones, seguridad y packaging importan solo si refuerzan el eje WhatsApp-first + ventas complejas + cotización segura + expediente trazable.

Prioridades:

* pricing/packaging;
* PWA;
* integraciones básicas;
* seguridad mínima vendible;
* exports;
* SLA/monitoring;
* admin de canales;
* plantillas verticales.

Resultado esperado:

```text
AtendIA se puede vender, configurar, operar, medir y soportar
sin depender de intervención técnica constante.
```

---

## 11. Backlog priorizado con criterios de aceptación

| Prioridad | Épica                     | Criterios de aceptación                                                                           |
| --------- | ------------------------- | ------------------------------------------------------------------------------------------------- |
| P0        | Autoridad final única     | Solo `AgentFinalResponse` emite mensaje visible; no hay doble respuesta; todo mensaje tiene trace |
| P0        | StateWriteGateway         | Toda escritura tiene fuente, evidencia, confianza, trace y rollback                               |
| P0        | Tools facts-only          | Tools de catálogo/requisitos/FAQ devuelven datos estructurados; no redactan mensaje final libre   |
| P0        | Canaries conversacionales | Casos de precio, buró, documentos, humano, contradicción y respuestas cortas pasan sin regresión  |
| P0        | WhatsApp runtime robusto  | Dedupe, outbox, retry, status, ventana 24h, pausa humana y logs                                   |
| P1        | Onboarding tenant         | Admin conecta WhatsApp, carga catálogo/requisitos/FAQ, prueba y publica sin código                |
| P1        | Vistas guardadas de inbox | Míos, sin asignar, docs pendientes, cotización enviada, handoff, alto valor                       |
| P1        | Pipeline reports          | Conversión, drop-off, tiempo por etapa, etapa actual, motivo de pérdida                           |
| P1        | Documentos por plan       | Estados claros, validación, revisión, impacto en etapa                                            |
| P1        | Followups básicos         | Opt-out, frecuencia, templates, pausa si responde cliente/humano                                  |
| P2        | Why-this-answer           | Cada respuesta muestra intención, tool, fuente, estado, confianza y regla                         |
| P2        | KB Command Center real    | Preguntas sin respuesta, conflictos, vigencia, tests y riesgos reales                             |
| P2        | Replay/A-B                | Probar agentes nuevos con conversaciones históricas sin side effects                              |
| P2        | Handoff learning loop     | Feedback humano alimenta backlog de FAQ/reglas/prompts/tools                                      |
| P2        | Money dashboard           | Valor potencial, cotizado, etapa, pérdida, modelo, asesor/agente                                  |
| P3        | Integraciones             | Webhooks, API, Zapier/Make/n8n, HubSpot/Salesforce según demanda                                  |
| P3        | Seguridad                 | 2FA, permisos finos, audit exportable, retention, backups, secrets                                |
| P3        | PWA/mobile                | Notificaciones, tomar conversación, responder, ver contacto/documentos                            |

---

## 12. Arquitectura recomendada del runtime

Flujo recomendado:

```text
Inbound webhook
  ↓
Normalizer + Dedupe
  ↓
Conversation State Builder
  ↓
NLU / Entity Resolver
  ↓
Business Runner
  ↓
Tool Orchestrator
  ↓
StateWriteGateway
  ↓
Response Planner
  ↓
Composer
  ↓
AgentFinalResponse
  ↓
OutboundGuard
  ↓
Outbox Worker
  ↓
Channel Sender
  ↓
Trace / Metrics / Audit
```

### Principios de diseño

1. **El estado manda, pero no secuestra la conversación.**
   El pipeline orienta; no convierte al asesor en formulario.

2. **La pregunta actual va primero.**
   Si el cliente pregunta precio, se responde/prepara precio antes de pedir documentos.

3. **El LLM redacta, pero no inventa facts.**
   Precios, requisitos y políticas vienen de tools/fuentes.

4. **Los tools devuelven evidencia, no improvisación.**

5. **Cada respuesta debe ser explicable.**

6. **Cada escritura de estado debe ser reversible.**

7. **Humano puede tomar control en cualquier momento.**

---

## 13. UX recomendada

### 13.1. Para asesor humano

El asesor necesita ver rápido:

* qué quiere el cliente;
* qué modelo/plan/enganche tiene;
* qué falta;
* qué dijo la IA;
* por qué escaló;
* qué sugerencia de respuesta hay;
* cuál es el siguiente paso.

Vista ideal:

```text
Chat al centro
Datos comerciales a la derecha
Timeline/trace resumido debajo o lateral
Acciones rápidas arriba: tomar, pausar, cotizar, pedir docs, mover etapa
```

### 13.2. Para gerente

El gerente necesita:

* embudo;
* leads atorados;
* asesores con carga;
* alto valor sin atender;
* errores de IA;
* motivos de pérdida;
* documentos bloqueantes;
* valor potencial.

### 13.3. Para admin

El admin necesita:

* conectar canal;
* cargar catálogo;
* editar requisitos;
* editar FAQ;
* probar agente;
* ver fallos;
* publicar/rollback;
* configurar pipeline;
* configurar permisos.

---

## 14. Recomendaciones comerciales

### 14.1. Paquetes posibles

No es pricing definitivo, pero sí estructura de packaging.

#### Paquete Piloto

Para validar con un cliente.

Incluye:

* 1 WhatsApp;
* 1 agente IA;
* catálogo básico;
* requisitos/documentos;
* inbox;
* pipeline;
* handoff;
* dashboard básico;
* soporte de implementación.

Objetivo: demostrar mejora en atención y cotización.

#### Paquete Growth

Para operación real.

Incluye:

* múltiples asesores;
* vistas guardadas;
* followups;
* reportes de funnel;
* replay de agente;
* KB Command Center básico;
* exports;
* roles.

Objetivo: operación diaria y seguimiento.

#### Paquete Custom/Enterprise

Para clientes con más requisitos.

Incluye:

* integraciones;
* permisos avanzados;
* auditoría/export;
* PWA;
* seguridad avanzada;
* deployment dedicado si aplica.

Objetivo: control, seguridad e integración.

### 14.2. Métrica comercial para vender AtendIA

AtendIA debería venderse con métricas antes/después:

* tiempo promedio de primera respuesta;
* porcentaje de leads cotizados;
* porcentaje de conversaciones con siguiente paso claro;
* documentos completos por lead;
* handoffs correctos;
* leads perdidos por falta de seguimiento;
* citas generadas;
* cierres atribuibles o asistidos;
* errores de cotización;
* horas humanas ahorradas.

### 14.3. Demo recomendada

La demo debe contar una historia.

Escenario:

```text
Cliente: Hola, me interesa la Adventure, traigo buró y me pagan por fuera.
```

AtendIA debería:

1. entender modelo/interés/crédito/buró/ingreso informal;
2. responder natural;
3. explicar política de forma segura;
4. pedir solo el dato faltante crítico;
5. cotizar con catálogo real cuando tenga datos;
6. mover pipeline;
7. sugerir documentos según plan;
8. mostrar trace de por qué respondió;
9. escalar si hay riesgo.

Ese demo vende mejor que mostrar 20 pantallas.

---

## 15. Qué no construir todavía

Esta sección debe leerse como una decisión de foco, no como falta de ambición. AtendIA no debe perseguir todo lo que una plataforma horizontal madura ya tiene; debe concentrar energía en ganar donde el comprador siente dinero perdido: WhatsApp, venta compleja, cotización, documentos, handoff y trazabilidad.

### 15.1. Omnicanalidad completa

No perseguir WhatsApp + Instagram + Messenger + Telegram + email + webchat + voz al mismo tiempo. Eso es la batalla de respond.io.

Construir primero WhatsApp excelente.

### 15.2. Workflow builder demasiado amplio

Un canvas tipo respond.io puede esperar si el agente todavía repite, inventa o escribe mal estado.

Primero templates verticales y DAG legible.

### 15.3. Mobile nativo

Primero PWA y notificaciones críticas.

### 15.4. Certificaciones enterprise

Primero seguridad práctica y evidencias. Certificaciones solo si hay cliente que lo justifique.

### 15.5. Broadcast masivo avanzado

Primero followups con opt-out, ventanas y trazabilidad. Broadcast completo después.

### 15.6. Configuración infinita

AtendIA debe ser configurable, pero no convertirse en un monstruo genérico. La ventaja es ser opinionado en ventas complejas.

---

## 16. Riesgos y mitigaciones

| Riesgo                              | Impacto                                           | Mitigación                                               |
| ----------------------------------- | ------------------------------------------------- | -------------------------------------------------------- |
| Muchas capas redactan/deciden       | Respuestas duplicadas, inconsistentes o robóticas | Autoridad final única y tests de doble emisión           |
| Escrituras de estado sin evidencia  | Pipeline/cliente contaminado                      | StateWriteGateway con provenance y rollback              |
| Catálogo desactualizado             | Cotizaciones incorrectas                          | Vigencia, validación, alertas y quote snapshots          |
| KB con conflictos                   | IA responde políticas contradictorias             | Conflict detection y tests de conocimiento               |
| UI con mocks                        | Falsa sensación de producto terminado             | Marcar experimental, cerrar mocks críticos o esconderlos |
| Falta de onboarding                 | Dependencia de developers                         | Wizard tenant y validadores                              |
| Reportes débiles                    | Gerente no ve ROI                                 | Dashboard de funnel/dinero/leads                         |
| Followups mal controlados           | Spam o mala experiencia                           | Opt-out, frecuencia, ventana 24h, pausa por humano       |
| Intentar copiar respond.io completo | Roadmap infinito                                  | Enfoque WhatsApp-first y vertical                        |
| Falta de integración                | Dato queda encerrado                              | Webhooks/API/export primero                              |

---

## 17. Score revisado

Separaría potencial de producto terminado.

| Área                    | AtendIA potencial | AtendIA hoy según reporte | respond.io | Comentario                                               |
| ----------------------- | ----------------: | ------------------------: | ---------: | -------------------------------------------------------- |
| WhatsApp sales vertical |                 5 |                       3.5 |          3 | AtendIA puede ganar si estabiliza runtime                |
| Omnicanalidad           |                 2 |                         1 |          5 | No competir aquí todavía                                 |
| Inbox operativo         |                 4 |                         3 |          5 | AtendIA necesita vistas guardadas y UX diaria            |
| Cotización              |                 5 |                         4 |          3 | Ventaja clara si catálogo está gobernado                 |
| Documentos/expediente   |                 5 |                         4 |          2 | Diferenciador fuerte                                     |
| IA vertical             |                 5 |                         3 |          4 | AtendIA puede ganar, pero necesita confianza operacional |
| IA producto listo       |                 4 |                       2.5 |          5 | respond.io está más empaquetado                          |
| Reportes ejecutivos     |                 4 |                         2 |          5 | AtendIA debe hablar dinero/funnel                        |
| Observabilidad IA       |                 5 |                         4 |          3 | Ventaja si se vuelve usable                              |
| Workflows backend       |                 4 |                         4 |          5 | AtendIA fuerte, respond.io más maduro                    |
| Workflows UX            |                 4 |                       2.5 |          5 | Falta canvas/templates o DAG claro                       |
| Integraciones           |                 4 |                         2 |          5 | Priorizar webhooks/API/Zapier/Make                       |
| Seguridad enterprise    |                 4 |                         2 |          5 | No es P0 salvo cliente enterprise                        |
| Time-to-value           |                 4 |                         2 |          5 | Onboarding guiado es clave                               |
| Defensibilidad vertical |                 5 |                       3.5 |          3 | La ventaja está en profundidad de negocio                |

---

## 18. Recomendación final mejorada

La recomendación final queda así:

> No construyas AtendIA para ser respond.io. Construye AtendIA para ser el mejor asesor comercial IA de WhatsApp en ventas con cotización, crédito, documentos y seguimiento.

Para lograrlo, el orden correcto es:

1. **Confiabilidad del cerebro:** una respuesta final, estado seguro, tools con evidencia, canaries.
2. **Operación diaria:** inbox, pipeline, documentos, handoff, followups, dashboard.
3. **Diferenciación:** why-this-answer, quote confidence, expediente inteligente, replay, KB health.
4. **Comercialización:** onboarding, paquetes, PWA, integraciones, seguridad y métricas de ROI.

La idea más importante:

```text
AtendIA no debe ganar por tener más features.
Debe ganar porque en el canal más importante del cliente,
la IA vende mejor, se equivoca menos, explica más y deja menos dinero perdido.
```

---

## 19. Prompt sugerido para Codex

Puedes usar este prompt para pedirle a Codex que convierta esta revisión en tareas técnicas:

```text
Lee reports/atendia-vs-respondio-2026-05-31.md y la revisión mejorada.
Crea un plan de implementación en issues/tickets para cerrar la Fase 0 y Fase 1.

Prioriza:
1. Autoridad final única de respuesta con AgentFinalResponse.
2. StateWriteGateway obligatorio para campos comerciales sensibles.
3. Canaries conversacionales para precio, buró, documentos, humano, contradicción y respuestas cortas.
4. Tools facts-only para catálogo, requisitos, FAQ y quote.
5. Vistas guardadas de inbox: míos, sin asignar, docs pendientes, cotización enviada, handoff y alto valor.
6. Pipeline reports mínimos: conversión, drop-off, tiempo por etapa y motivo de pérdida.
7. Onboarding tenant: conectar WhatsApp, cargar catálogo, requisitos, FAQ, probar agente y publicar.

Para cada ticket incluye:
- objetivo;
- archivos probables;
- cambios backend;
- cambios frontend;
- migraciones si aplica;
- criterios de aceptación;
- tests/canaries;
- riesgos.

No implementes omnicanalidad, mobile nativo, certificaciones ni workflow canvas avanzado hasta cerrar P0/P1.
```
