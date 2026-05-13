# AtendIA Baileys Bridge

Sidecar Node.js que expone [Baileys](https://github.com/WhiskeySockets/Baileys) (cliente NO oficial de WhatsApp basado en el protocolo de WhatsApp Web) como una API HTTP que el backend Python de AtendIA consume.

Diseño completo en `docs/plans/2026-05-13-baileys-integration-design.md`.

## Por qué un sidecar

Baileys es ESM puro Node — no se puede importar desde Python. En vez de re-implementar el protocolo de WhatsApp Web en Python (años de trabajo), corremos Baileys aparte y hablamos HTTP entre los dos procesos.

## Arranque local (sin Docker)

```bash
cd core/baileys-bridge
npm install
INTERNAL_TOKEN=dev-token PORT=7755 npm start
```

Health-check:
```bash
curl -s http://localhost:7755/healthz
# → {"ok":true,"sessions":0,"uptime_s":3}
```

Llamadas con auth interno:
```bash
curl -s http://localhost:7755/sessions/<tenant-uuid>/status \
  -H "X-Internal-Token: dev-token"
```

## Arranque vía docker-compose

Cableado en `docker-compose.yml` del root del repo (T8). El sidecar comparte red con `atendia-backend` y monta un volumen `baileys_auth` para persistir la sesión entre reinicios.

```bash
docker compose up -d baileys-bridge
docker compose logs -f baileys-bridge
```

## Variables de entorno

| Variable | Default | Para qué |
|---|---|---|
| `PORT` | `7755` | Puerto HTTP del sidecar |
| `HOST` | `0.0.0.0` | Bind interface |
| `INTERNAL_TOKEN` | (requerido) | Shared secret con el backend; sin él, todas las rutas devuelven 403 |
| `AUTH_DIR` | `/app/auth_info` | Dir raíz para `auth_info/<tenant>/` |
| `ATENDIA_API_BASE` | `http://atendia-backend:8001` | URL del backend para enviar inbound webhooks (T4) |
| `LOG_LEVEL` | `info` | `debug` para tracing detallado |

## Endpoints

| Método | Path | Estado |
|---|---|---|
| `GET` | `/healthz` | ✓ (público) |
| `POST` | `/sessions/:tid/connect` | T3 |
| `GET` | `/sessions/:tid/qr` | ✓ (vacío hasta T3) |
| `GET` | `/sessions/:tid/status` | ✓ (devuelve `disconnected` hasta T3) |
| `POST` | `/sessions/:tid/disconnect` | T3 |
| `POST` | `/sessions/:tid/send` | T4 |

Todos excepto `/healthz` requieren header `X-Internal-Token`.

## Por qué no hay UI ni Electron

El sidecar es sólo un puente HTTP. La UI (QR + estado + connect/disconnect) vive en el frontend React principal de AtendIA — pestaña `/config` → Integraciones. Ver T9.

## Por qué NO hay stealth / proxy / campaigns

Lo trae la WASenderApp original (Electron desktop), pero AtendIA no lo necesita: aquí el caso es un solo número del operador escaneando QR, no spam masivo. Phase 2 si alguna vez se requiere.
