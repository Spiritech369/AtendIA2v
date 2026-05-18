# Sprint 2 browser + WhatsApp sandbox findings

Fecha: 2026-05-16
Cuenta usada: `test@test.com` / `test123`
Tenant: `a3e469f2-06ed-4d23-ada2-124fe6993271`
Frontend validado: `http://localhost:5173`

## Resumen ejecutivo

Actualizacion post-fix (2026-05-16):

- Pipeline: `Configurar etapas` abre el editor y muestra `Ocultar editor`, `Guardar` y catalogo de documentos.
- WhatsApp Meta: `Probar webhook` dispara un sandbox real desde UI, crea conversacion/mensaje/trace y actualiza status a `Conectado`; el outbound sandbox queda como `Mensaje enviado` simulado, sin llamada a Meta real.
- Knowledge: `Probar fuente` en `SKU DINM-U5-2024 - Dinamo U5` recupera chunks de `Catalogo: DINM-U5-2024 - Dinamo U5` y muestra la respuesta simulada.
- `/conversations`: redirige a `/` y renderiza la bandeja.
- Tenant `test@test.com`: reseteado como `Dinamo Beta Demo`, `is_demo=false`, con 1 pipeline activo, 1 Agent IA, 3 catalog items, 5 FAQs y datos runtime limpios antes del sandbox.
- Smoke formal: `pnpm exec playwright test tests/e2e/smoke-routes.spec.ts --reporter=list` paso 7/7.

## Hallazgos originales

La UI real ya permite operar las superficies principales con el usuario de prueba:
Agentes IA, Knowledge, Conversaciones, Workflows y DebugPanel cargan sin errores de consola visibles.
WhatsApp sandbox llega hasta QR de Baileys, pero el flujo de prueba de webhook Meta no es un sandbox clicable completo.

Hay 4 gaps que conviene arreglar antes de llamar vendible al Sprint 2:

1. Pipeline: `Configurar etapas` no abre un editor visible desde el Kanban.
2. WhatsApp: el status global dice `Meta: sin actividad`, pero Integraciones dice WhatsApp `Conectado`.
3. WhatsApp: `Probar webhook` solo muestra instrucciones; no ejecuta una prueba end-to-end desde la UI.
4. Knowledge: catalogo existe y se puede seleccionar, pero `Probar fuente` no demuestra claramente que la respuesta simulada use el catalogo; sigue mostrando `Fuente: 2 documentos`.

## Evidencia por area

| Area | Estado | Evidencia browser |
| --- | --- | --- |
| Login/session | PASS | Sesion activa como `test@test.com`, rol `Admin tenant`, tenant `a3e469f2`. |
| Agentes IA | PASS parcial | `/agents` carga 6 perfiles demo, tabs `Resumen`, `Identidad`, `Guardrails`, `Knowledge`, `Extraccion`, `Decision Map`, `Pruebas`, `Historial`. Sin errores de consola. |
| Pipeline | GAP alto | `/pipeline` carga `42 conversaciones`, `9 etapas` y tarjetas por etapa. Al pulsar `Configurar etapas`, no aparece editor/drawer ni controles de guardado/configuracion en el DOM. |
| Knowledge | PASS parcial | `/knowledge` carga `FAQs 156`, `Catalogo 642`, `Documentos 412`. El tab `Catalogo` muestra `SKU DINM-U5-2024 - Dinamo U5` y `SKU DINM-R1-2024 - Dinamo R1`. |
| Knowledge test | GAP medio | `Probar fuente` sobre Dinamo U5 se puede pulsar, pero la vista de respuesta simulada conserva texto generico y cita `Fuente: 2 documentos`, no una fuente de catalogo. |
| Conversaciones | PASS parcial | `/` carga bandeja con `Conversaciones 92`, filtros por etapa, detalle de chat, mensajes, input y link `Abrir WhatsApp`. |
| Conversaciones route | GAP bajo | `/conversations` devuelve `Not Found`; la navegacion real apunta a `/`. Conviene redireccionar para evitar links rotos o bookmarks fallidos. |
| Pipeline data coherence | GAP medio | La bandeja muestra muchas etapas `sin pipeline` como `documentation`, `in_conversation`, `new`, `qualified`. No rompe la vista, pero ensucia la experiencia operador. |
| Workflows | PASS | `/workflows` muestra `6 workflows`, canvas publicado de solo lectura, nodos, disparador `Cambio de etapa`, opciones `Entro a etapa`, `Cambio de etapa`, y panel de simulacion. |
| DebugPanel | PASS | `/turn-traces` muestra actividad reciente del runner, `99+` traces, links por conversacion y tabla con `Modo`, `Mensaje`, `NLU`, `Composer`, `Latencia`, `Costo USD`. |
| WhatsApp Meta | GAP alto | Sidebar: `Meta: sin actividad`. Integraciones: WhatsApp Business API `Conectado`, credenciales presentes y webhook recibido en ultimas 24h. Mensaje contradictorio. |
| WhatsApp webhook test | GAP alto | Boton `Probar webhook` no dispara test real; muestra notificacion: `Para probar el webhook, envia una solicitud GET desde Meta Business Manager.` |
| WhatsApp Baileys QR | PASS parcial | `Conectar con WhatsApp` pasa de `Desconectado` a `Conectando`, luego el sidebar muestra `Baileys: emparejando` y aparece imagen `Codigo QR para vincular WhatsApp`. |

## Limitacion de la prueba

La automatizacion del navegador no pudo escribir en textboxes porque el entorno reporta `Browser Use virtual clipboard is not installed`.
Esto afecto pruebas de texto como buscar `Dinamo U5` desde el buscador de Knowledge o usar cajas de prueba del agente.
No se marco como bug del producto porque la UI si renderiza los inputs; hace falta una pasada manual o un harness browser con entrada de texto confiable.

## Fixes recomendados antes de cerrar Sprint 2

1. Hacer que `Configurar etapas` en Pipeline abra el editor real o navegue a la configuracion correcta.
2. Reconciliar el badge global de WhatsApp con el estado de Integraciones: Meta conectado/no activo y Baileys emparejando/desconectado deben tener definiciones consistentes.
3. Cambiar `Probar webhook` por un sandbox real: disparar evento local controlado, mostrar request/response, conversacion creada/actualizada y trace asociado.
4. Mejorar `Probar fuente` de Knowledge para que, al probar una fuente de catalogo, el panel cite explicitamente SKU, coleccion y resultado de recuperacion del catalogo.
5. Agregar redirect de `/conversations` a `/` o mover la bandeja a `/conversations` y mantener `/` como redirect.
6. Normalizar o migrar estados legacy `sin pipeline` en datos demo para que no se mezclen con etapas reales del pipeline moto/venta.

## Criterio de cierre Sprint 2

Sprint 2 queda cerrado cuando un operador pueda, desde navegador y con `test@test.com`:

1. Probar Agente IA y Knowledge escribiendo una consulta real.
2. Abrir configuracion de pipeline desde Kanban.
3. Disparar webhook/sandbox WhatsApp desde UI sin depender de Meta Business Manager.
4. Ver la conversacion generada, el cambio de etapa/workflow si aplica, y el trace del runner en DebugPanel.
