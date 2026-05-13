// Route registrations. Baileys-backed handlers land in T3+; for now we
// expose just the placeholders that respond with 501 so the backend
// integration can be tested against the contract early.

import { sessionFor } from './session-manager.js'

export function registerRoutes(app) {
  app.post('/sessions/:tid/connect', async (_req, reply) => {
    reply.code(501).send({ error: 'not_implemented', task: 'T3' })
  })

  app.get('/sessions/:tid/qr', async (req) => {
    const s = sessionFor(req.params.tid)
    if (s.status !== 'qr_pending' || !s.qrDataUrl) {
      return { qr: null, status: s.status }
    }
    return { qr: s.qrDataUrl, status: s.status }
  })

  app.get('/sessions/:tid/status', async (req) => {
    const s = sessionFor(req.params.tid)
    return {
      status: s.status,
      phone: s.phone,
      last_status_at: s.statusAt.toISOString(),
      reason: s.statusReason,
    }
  })

  app.post('/sessions/:tid/disconnect', async (_req, reply) => {
    reply.code(501).send({ error: 'not_implemented', task: 'T3' })
  })

  app.post('/sessions/:tid/send', async (_req, reply) => {
    reply.code(501).send({ error: 'not_implemented', task: 'T4' })
  })
}
