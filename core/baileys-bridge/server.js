// AtendIA Baileys bridge — Fastify HTTP server.
//
// Routes are added in src/routes.js as the feature lands across tasks.
// Today (T2) the server only exposes /healthz so we can verify the
// container starts and the backend can reach it.

import Fastify from 'fastify'
import { listSessions } from './src/session-manager.js'
import { registerRoutes } from './src/routes.js'

const PORT = Number(process.env.PORT || 7755)
const HOST = process.env.HOST || '0.0.0.0'
const INTERNAL_TOKEN = process.env.INTERNAL_TOKEN || ''

const app = Fastify({
  logger: {
    level: process.env.LOG_LEVEL || 'info',
    transport: process.env.NODE_ENV === 'production' ? undefined : { target: 'pino-pretty' },
  },
})

// Internal-token guard for every route except /healthz.
app.addHook('onRequest', async (req, reply) => {
  if (req.url === '/healthz') return
  const provided = req.headers['x-internal-token']
  if (!INTERNAL_TOKEN || provided !== INTERNAL_TOKEN) {
    reply.code(403).send({ error: 'forbidden' })
  }
})

app.get('/healthz', async () => ({
  ok: true,
  sessions: listSessions().length,
  uptime_s: Math.round(process.uptime()),
}))

registerRoutes(app)

app
  .listen({ port: PORT, host: HOST })
  .then(() => {
    app.log.info({ port: PORT }, 'baileys-bridge listening')
  })
  .catch((err) => {
    app.log.error({ err }, 'baileys-bridge failed to start')
    process.exit(1)
  })
