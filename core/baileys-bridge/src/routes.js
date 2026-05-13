// HTTP route definitions for the sidecar. Auth (X-Internal-Token) is
// enforced globally in server.js via a Fastify onRequest hook.

import { getSession, sendText, startSession, stopSession } from './baileys.js'
import { sessionFor } from './session-manager.js'

export function registerRoutes(app) {
  app.post('/sessions/:tid/connect', async (req, reply) => {
    try {
      const snapshot = await startSession(req.params.tid, app.log)
      return snapshot
    } catch (err) {
      app.log.error({ err, tid: req.params.tid }, 'connect failed')
      reply.code(500).send({ error: 'connect_failed', message: err?.message })
    }
  })

  app.get('/sessions/:tid/qr', async (req) => {
    const s = sessionFor(req.params.tid)
    if (s.status !== 'qr_pending' || !s.qrDataUrl) {
      return { qr: null, status: s.status }
    }
    return { qr: s.qrDataUrl, status: s.status }
  })

  app.get('/sessions/:tid/status', async (req) => getSession(req.params.tid))

  app.post('/sessions/:tid/disconnect', async (req, reply) => {
    try {
      return await stopSession(req.params.tid, app.log)
    } catch (err) {
      app.log.error({ err, tid: req.params.tid }, 'disconnect failed')
      reply.code(500).send({ error: 'disconnect_failed', message: err?.message })
    }
  })

  app.post('/sessions/:tid/send', async (req, reply) => {
    const { to_phone, text } = req.body || {}
    if (!to_phone || !text) {
      reply.code(400).send({ error: 'missing_fields', need: ['to_phone', 'text'] })
      return
    }
    try {
      return await sendText(req.params.tid, to_phone, text, app.log)
    } catch (err) {
      app.log.error({ err, tid: req.params.tid }, 'send failed')
      reply.code(500).send({ error: 'send_failed', message: err?.message })
    }
  })
}
