# Baileys WhatsApp QR — integración como canal alternativo

**Fecha:** 2026-05-13
**Branch:** `claude/beautiful-mirzakhani-55368f`
**Autor:** Claude + zpiritech369@gmail.com

Agregar un canal de WhatsApp por QR (Baileys, no oficial) al lado del
Meta Cloud API existente, dentro de `/config` → Integraciones. El
operador escanea un QR desde su WhatsApp Business (el de la app móvil)
y a partir de ahí AtendIA puede enviar y recibir por ese número.
Permite probar el sistema con un número real sin migrar todavía a
Meta Business API verificado.

## Contexto y restricciones técnicas

- **Baileys es ESM puro Node.js** — imposible importar desde Python.
  Solución: sidecar Node aparte que el backend Python invoca por HTTP.
- **Baileys NO es oficial** — usa el protocolo de WhatsApp Web por
  reverse engineering. Meta puede banear números. Para el caso de uso
  del usuario (su propio número, sin masivos), el riesgo es aceptable
  y similar al de tener WhatsApp Web abierto en una pestaña.
- **Sesión persistente** vive en filesystem (`auth_info/<tenant_id>/`)
  — usaremos un volumen Docker dedicado para sobrevivir reinicios.
- **No hacemos campañas masivas, stealth, fingerprinting ni proxy
  rotation** — la WASenderApp original las trae pero son irrelevantes
  para este caso (el usuario no quiere blast).

## Arquitectura

```
React (Vite)              FastAPI (Python)              Sidecar Node.js
/config/integrations      /api/v1/integrations/         /sessions/:tid/...
                          baileys/{status,connect,..}    HTTP+long-poll
                          /api/v1/internal/baileys/      :7755 interno
                          inbound  ←─ webhook desde sidecar
                                                       │
                                                       ▼
                                                 auth_info/<tenant>/
                                                 (Docker volume)
```

Bidirectional:
- **Outbound**: backend → sidecar → Baileys → WhatsApp
- **Inbound**: WhatsApp → Baileys → sidecar POST a backend
  `/api/v1/internal/baileys/inbound` → mismo flujo que webhook Meta

## Componentes nuevos

### 1. `core/baileys-bridge/` (microservicio Node.js)

```
core/baileys-bridge/
├── Dockerfile
├── package.json              # dependencias mínimas
├── server.js                 # Fastify HTTP + routes
├── baileys.js                # connect/QR/send/inbound listener
├── session-manager.js        # per-tenant auth_info paths
├── webhook-client.js         # POST inbound to AtendIA
└── README.md
```

Dependencias mínimas (vs las 9 de WASenderApp): solo
`@whiskeysockets/baileys`, `pino`, `qrcode`, `fastify`. Sin Electron,
Playwright, xlsx, proxy-agents, dotenv (env vars vía Docker).

Endpoints internos (puerto 7755, no expuesto público):

| Método | Path | Body | Respuesta |
|---|---|---|---|
| POST | `/sessions/:tid/connect` | — | `{status: 'connecting'\|'qr_pending'\|'connected', phone?}` |
| GET | `/sessions/:tid/qr` | — | `{qr: 'data:image/png;base64,...'}` o `404` si ya conectado |
| GET | `/sessions/:tid/status` | — | `{status, phone?, last_status_at}` |
| POST | `/sessions/:tid/disconnect` | — | `{status: 'disconnected'}` |
| POST | `/sessions/:tid/send` | `{to_phone, text}` | `{message_id, sent_at}` |
| GET | `/healthz` | — | `{ok: true, sessions: N}` |

Auth: header `X-Internal-Token` requerido en todos los endpoints (compartido con backend vía env var).

Eventos del listener de Baileys:
- `connection.update` → si hay `qr`, generar PNG y guardar en memoria.
  Si `connection==='open'`, marcar `connected` + `phone`. Si
  `connection==='close'` y no fue `loggedOut`, reconectar en 5s.
- `messages.upsert` → si `type==='notify'` y NO fromMe → POST a
  `{ATENDIA_API}/api/v1/internal/baileys/inbound` con
  `{tenant_id, from_phone, text, ts, message_id}` y header
  `X-Internal-Token`.

### 2. Migración 042 — `tenant_baileys_config`

```sql
CREATE TABLE tenant_baileys_config (
  tenant_id      UUID PRIMARY KEY REFERENCES tenants(id) ON DELETE CASCADE,
  enabled        BOOL NOT NULL DEFAULT false,
  connected_phone TEXT,
  last_status    TEXT NOT NULL DEFAULT 'disconnected',
  last_status_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  prefer_over_meta BOOL NOT NULL DEFAULT false,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE tenant_baileys_config
  ADD CONSTRAINT ck_baileys_status
  CHECK (last_status IN ('disconnected','connecting','qr_pending','connected','error'));
```

### 3. Backend `core/atendia/api/baileys_routes.py`

```
GET    /api/v1/integrations/baileys/status            → tenant-scoped status
POST   /api/v1/integrations/baileys/connect            → starts session, returns initial state
POST   /api/v1/integrations/baileys/disconnect         → tears down session, clears auth
GET    /api/v1/integrations/baileys/qr                 → returns PNG base64 if pending
PATCH  /api/v1/integrations/baileys/preference         → {prefer_over_meta: bool}
POST   /api/v1/integrations/baileys/test-send          → utilitario, dev-only
POST   /api/v1/internal/baileys/inbound                → callback desde sidecar (X-Internal-Token)
```

Auth: routes públicas usan `current_user` + `current_tenant_id` (operator+ para read, tenant_admin+ para mutate). El `/internal/` valida `X-Internal-Token` y NO requiere user.

`baileys_client.py` (cliente HTTP al sidecar) — wrap async httpx con timeout 5s. Usado por las routes públicas.

### 4. Cableado de inbound al `conversation_runner`

`/api/v1/internal/baileys/inbound` hace:

1. Valida `X-Internal-Token`.
2. Resuelve o crea `Customer` por `phone_e164 = from_phone`.
3. Resuelve o crea `Conversation` activa para ese customer.
4. Inserta `MessageRow` (direction='inbound', source='baileys', body=text).
5. Marca `whatsapp:last_at:<tenant_id>` en Redis (para que el channel
   status badge funcione).
6. Llama `await runner.run_turn(conversation_id, message_id)` —
   mismo path que `meta_routes.py`.

Diferencia clave vs Meta webhook: no hay verificación firmada (Baileys
no firma webhooks porque viene de nuestro propio sidecar). El
`X-Internal-Token` es la barrera.

### 5. Cableado de outbound — `OutboundDispatcher`

Hoy `OutboundDispatcher.send_text(tenant_id, to, text)` siempre va a
`MetaCloudAPI`. Cambio:

```python
async def send_text(self, tenant_id, to, text):
    cfg = await self._get_baileys_config(tenant_id)
    if cfg and cfg.enabled and cfg.prefer_over_meta and cfg.last_status == 'connected':
        return await self._baileys.send_text(tenant_id, to, text)
    return await self._meta.send_text(tenant_id, to, text)
```

`_get_baileys_config` cachea con TTL 30s para no consultar DB en cada
mensaje outbound durante una campaña.

### 6. Frontend `IntegrationsTab.tsx`

Card nueva debajo de la card existente de Meta. Estados:

- **Disconnected**: botón "Conectar con WhatsApp"
- **Connecting**: spinner + "Iniciando sesión…"
- **QR Ready**: muestra `<img src={qr_data_url}>` con instrucción
  "Abre WhatsApp → Configuración → Dispositivos vinculados → Vincular
  un dispositivo → escanea este código". Polling de status cada 3s.
- **Connected**: muestra teléfono + "Desconectar" + switch "Usar
  este canal en lugar de Meta Business API"
- **Error**: muestra mensaje + botón "Reintentar"

### 7. Docker compose

Nuevo servicio:

```yaml
baileys-bridge:
  build:
    context: ./core/baileys-bridge
  ports:
    - "7755:7755"  # interno; sólo accesible vía atendia-backend
  volumes:
    - baileys_auth:/app/auth_info
  environment:
    PORT: "7755"
    ATENDIA_API_BASE: "http://atendia-backend:8001"
    INTERNAL_TOKEN: "${BAILEYS_INTERNAL_TOKEN:-dev-token-change-me}"
  restart: unless-stopped
  healthcheck:
    test: ["CMD", "wget", "-q", "-O", "-", "http://localhost:7755/healthz"]
    interval: 30s

volumes:
  baileys_auth:
```

El backend lee `BAILEYS_BRIDGE_URL` (default `http://baileys-bridge:7755`)
y `BAILEYS_INTERNAL_TOKEN`.

## Estabilidad ("que no se desconecte")

| Mecanismo | Implementación |
|---|---|
| **Auto-reconnect** | Heredado de WASenderApp: `setTimeout(startWhatsApp, 5000)` en `connection: 'close'` salvo `DisconnectReason.loggedOut` |
| **Persistent auth** | Docker volume `baileys_auth` montado en `/app/auth_info` |
| **Status polling** | Backend cron cada 60s consulta sidecar y actualiza `last_status_at` |
| **Frontend polling** | Mientras estado es `connecting` o `qr_pending`, frontend pollea cada 3s |
| **Healthcheck sidecar** | Docker healthcheck → si falla, restart |
| **Logs estructurados** | `pino` en sidecar, INFO a stdout |

## YAGNI explícito

- Sin campañas masivas (delays gaussianos / blacklist / batch rest / spintax)
- Sin stealth / fingerprint / proxy / userAgent rotation
- Sin multimedia (imágenes/audio/docs) — Phase 2
- Sin multi-sesión por tenant (un teléfono por tenant)
- Sin auto-reply IA en el sidecar (lo hace el runner Python)
- Sin reset session UI separado (basta Desconectar + Reconectar)
- Sin métricas detalladas del sidecar (logs son suficientes para v1)
- Sin verificación de número en WhatsApp antes de enviar (`onWhatsApp`)
  — error de envío es respuesta suficiente para v1

## Riesgos a documentar

| Riesgo | Mitigación |
|---|---|
| Meta banea el número del usuario | El usuario asume el riesgo. Documentar en la card. |
| Sidecar muere y pierde mensajes en cola | Cola del sidecar es Baileys-interna; reconnect recupera mensajes del lado de WhatsApp |
| Inbound llega y backend no responde 200 | Sidecar reintenta 3 veces con backoff exponencial |
| Phone disconnected from primary device | Visible en estado `disconnected` con `last_status_reason='primary_unlinked'` |
| Token interno filtrado | Token sólo entre containers en red Docker privada; rotable vía env var |

## Tests

### Backend

- `test_baileys_routes.py`:
  - `test_status_unauth`: 401
  - `test_status_connected`: sidecar mockeado, parsea correctamente
  - `test_connect_starts_session`: sidecar mockeado, devuelve qr_pending
  - `test_disconnect_clears_auth`: sidecar mockeado
  - `test_preference_toggle_writes_db`: persiste en `tenant_baileys_config`
- `test_baileys_inbound.py`:
  - `test_inbound_requires_internal_token`: 403 sin token
  - `test_inbound_creates_message_and_calls_runner`: mockea runner, verifica MessageRow + invocación
- `test_outbound_dispatcher_baileys.py`:
  - `test_routes_to_meta_by_default`: prefer_over_meta=false → Meta
  - `test_routes_to_baileys_when_preferred_and_connected`: → sidecar
  - `test_falls_back_to_meta_if_baileys_disconnected`: → Meta aunque prefer=true

### Sidecar Node

- `node --test test/server.test.js` — smoke con auth_info pregrabado
  simulado (no contacta WhatsApp real). Verifica que endpoints
  responden con la shape esperada.

### Frontend

- `IntegrationsTab.test.tsx` ampliado: render de cada uno de los 5
  estados de la Baileys card.

## Orden de implementación (10 tasks)

1. **Migración 042 + modelo `TenantBaileysConfig`** + smoke alembic.
2. **Sidecar Node skeleton**: package.json, server.js con healthz,
   Dockerfile, README. Sin Baileys aún. Verificar levanta.
3. **Sidecar Baileys lógica**: connect/QR/disconnect, polling de
   status, persistencia en `auth_info/<tid>/`. Endpoints HTTP.
4. **Sidecar send_text + inbound webhook**: callback a backend con
   `X-Internal-Token`. Reintento 3x.
5. **Backend `baileys_client.py`** (httpx wrapper) + tests.
6. **Backend `baileys_routes.py`** (rutas públicas + internal/inbound)
   + 5 tests + 2 tests.
7. **Cableado outbound dispatcher**: lectura de config, fallback a
   Meta, 3 tests.
8. **docker-compose service** + env var `BAILEYS_INTERNAL_TOKEN` en
   `.env.example` + verificar `docker compose up` arranca el sidecar.
9. **Frontend `IntegrationsTab`**: 5 estados + polling + tests.
10. **Smoke E2E manual**: conectar QR real desde el browser, verificar
    mensaje entrante llega al inbox, enviar mensaje desde AtendIA por
    el sidecar. Update PROJECT_MAP. Merge a main.

## Criterios de éxito

- `docker compose up -d baileys-bridge atendia-backend` arranca ambos
  containers en estado healthy.
- Login en `/config` como tenant_admin → tab Integraciones muestra
  card "WhatsApp Personal (QR)" en estado Disconnected.
- Click "Conectar" → estado pasa a QR Ready, aparece código.
- Escanear QR desde un WhatsApp real → estado pasa a Connected con
  número visible.
- Enviar un mensaje al número conectado → aparece en el inbox de
  AtendIA igual que un Meta inbound.
- Toggle "Usar este canal en lugar de Meta" + responder un cliente
  desde el inbox → la respuesta llega al cliente vía Baileys.
- `docker compose restart baileys-bridge` → sesión recuperada del
  volumen, no requiere re-escanear QR.
- Backend tests + sidecar smoke + frontend tests verdes.
- Branch mergeada a `main` + push.
