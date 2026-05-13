// Per-tenant Baileys session manager.
//
// Each tenant has its own auth_info directory at `auth_info/<tenantId>/`
// so multi-tenancy stays clean. The session object holds the live socket
// + the most recent QR code (if pending) + the last status snapshot.

import { mkdirSync } from 'node:fs'
import path from 'node:path'

const AUTH_ROOT = process.env.AUTH_DIR || '/app/auth_info'

/** @type {Map<string, Session>} */
const sessions = new Map()

/**
 * @typedef {Object} Session
 * @property {string} tenantId
 * @property {string} authDir
 * @property {'disconnected'|'connecting'|'qr_pending'|'connected'|'error'} status
 * @property {string|null} qrDataUrl    Most recent QR (data: URL), null after connect.
 * @property {string|null} phone        E.164 once connected.
 * @property {Date} statusAt
 * @property {string|null} statusReason
 * @property {*} sock                   Baileys socket (or null).
 * @property {boolean} stopReconnect    True when disconnect() was called.
 */

export function sessionFor(tenantId) {
  let s = sessions.get(tenantId)
  if (!s) {
    const authDir = path.join(AUTH_ROOT, tenantId)
    mkdirSync(authDir, { recursive: true })
    s = {
      tenantId,
      authDir,
      status: 'disconnected',
      qrDataUrl: null,
      phone: null,
      statusAt: new Date(),
      statusReason: null,
      sock: null,
      stopReconnect: false,
    }
    sessions.set(tenantId, s)
  }
  return s
}

export function updateStatus(tenantId, status, extra = {}) {
  const s = sessionFor(tenantId)
  s.status = status
  s.statusAt = new Date()
  if ('reason' in extra) s.statusReason = extra.reason ?? null
  if ('phone' in extra) s.phone = extra.phone ?? null
  if ('qrDataUrl' in extra) s.qrDataUrl = extra.qrDataUrl ?? null
  return s
}

export function listSessions() {
  return Array.from(sessions.values()).map((s) => ({
    tenantId: s.tenantId,
    status: s.status,
    phone: s.phone,
    statusAt: s.statusAt.toISOString(),
  }))
}

export function dropSession(tenantId) {
  sessions.delete(tenantId)
}
