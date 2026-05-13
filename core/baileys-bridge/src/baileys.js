// Baileys lifecycle wrapper — connect / QR / disconnect.
//
// Simplificado a propósito vs la WASenderApp original: cero stealth,
// proxy, classifier IA, blacklist, historial. Solo el ciclo mínimo
// que un canal SaaS necesita.

import { rmSync, readdirSync, readFileSync } from 'node:fs'
import path from 'node:path'
import QRCode from 'qrcode'

import { sessionFor, updateStatus, dropSession } from './session-manager.js'
import { postInbound, postOutboundEcho } from './webhook-client.js'

// Auto-reconnect schedule per tenant — clear on disconnect() so the
// session stays down when the user explicitly logged out.
const reconnectTimers = new Map()

// Per-tenant LID→phone cache. WhatsApp sometimes sends messages from
// Linked Identity IDs instead of real phone numbers; we resolve them here.
const lidCaches = new Map()

function getLidCache(tenantId) {
  let cache = lidCaches.get(tenantId)
  if (!cache) {
    cache = new Map()
    lidCaches.set(tenantId, cache)
  }
  return cache
}

function loadLidMappingsFromDisk(authDir, cache, logger) {
  try {
    const files = readdirSync(authDir).filter(
      (f) => f.startsWith('lid-mapping-') && f.endsWith('_reverse.json'),
    )
    for (const f of files) {
      const lid = f.replace('lid-mapping-', '').replace('_reverse.json', '')
      try {
        const phone = JSON.parse(readFileSync(path.join(authDir, f), 'utf8'))
        if (typeof phone === 'string' && phone.length >= 8) {
          cache.set(lid, phone)
        }
      } catch { /* skip malformed files */ }
    }
    if (cache.size > 0) {
      logger.info({ count: cache.size }, 'loaded LID mappings from disk')
    }
  } catch { /* authDir may not exist yet */ }
}

function resolveLid(fromJid, cache) {
  if (!fromJid.includes('@lid')) return fromJid.split('@')[0]?.replace(/\D/g, '')
  const lid = fromJid.split(':')[0]?.replace(/\D/g, '')
  return cache.get(lid) || lid
}

// Extract a human-readable text out of any of the message variants WhatsApp
// emits. Plain text + extendedText covers the common case; the rest catch
// media captions and replies so an operator's photo with caption or a quote
// reply doesn't silently disappear from the AtendIA mirror.
//
// Returns the text or a placeholder marker like "[image]" when the message
// is media without a caption (so the conversation still reflects something
// happened, even if the media payload itself is out of scope for v1).
function extractMessageText(m) {
  if (!m) return null
  if (typeof m.conversation === 'string' && m.conversation) return m.conversation
  if (m.extendedTextMessage?.text) return m.extendedTextMessage.text
  if (m.imageMessage) return m.imageMessage.caption || '[imagen]'
  if (m.videoMessage) return m.videoMessage.caption || '[video]'
  if (m.documentMessage) {
    return m.documentMessage.caption || m.documentMessage.fileName || '[documento]'
  }
  if (m.audioMessage) return m.audioMessage.ptt ? '[nota de voz]' : '[audio]'
  if (m.stickerMessage) return '[sticker]'
  if (m.locationMessage) return '[ubicación]'
  if (m.contactMessage || m.contactsArrayMessage) return '[contacto]'
  // Some replies / forwards wrap the real content under
  // `ephemeralMessage.message` or `viewOnceMessage.message`. Unwrap one
  // level so captions still come through.
  if (m.ephemeralMessage?.message) return extractMessageText(m.ephemeralMessage.message)
  if (m.viewOnceMessage?.message) return extractMessageText(m.viewOnceMessage.message)
  if (m.viewOnceMessageV2?.message) return extractMessageText(m.viewOnceMessageV2.message)
  return null
}

function clearReconnect(tenantId) {
  const t = reconnectTimers.get(tenantId)
  if (t) {
    clearTimeout(t)
    reconnectTimers.delete(tenantId)
  }
}

function scheduleReconnect(tenantId, logger) {
  clearReconnect(tenantId)
  const session = sessionFor(tenantId)
  if (session.stopReconnect) return
  const t = setTimeout(() => {
    logger.info({ tenantId }, 'auto-reconnect attempt')
    startSession(tenantId, logger).catch((err) =>
      logger.error({ err, tenantId }, 'auto-reconnect failed'),
    )
  }, 5000)
  reconnectTimers.set(tenantId, t)
}

/**
 * Starts (or restarts) the Baileys socket for a tenant. Returns the
 * current status snapshot once the event loop has settled briefly.
 */
export async function startSession(tenantId, logger) {
  const session = sessionFor(tenantId)
  session.stopReconnect = false

  if (session.status === 'connected') {
    return statusOf(session)
  }

  updateStatus(tenantId, 'connecting', { reason: null })

  const baileys = await import('@whiskeysockets/baileys')
  const pinoMod = await import('pino')
  const pino = pinoMod.default

  const {
    default: makeWASocket,
    useMultiFileAuthState,
    DisconnectReason,
    fetchLatestBaileysVersion,
    makeCacheableSignalKeyStore,
  } = baileys

  const baileysLogger = pino({ level: 'silent' })

  const { state, saveCreds } = await useMultiFileAuthState(session.authDir)
  const { version } = await fetchLatestBaileysVersion()

  const lidCache = getLidCache(tenantId)
  loadLidMappingsFromDisk(session.authDir, lidCache, logger)

  logger.info({ tenantId, waVersion: version.join('.') }, 'starting baileys session')

  const sock = makeWASocket({
    version,
    logger: baileysLogger,
    auth: {
      creds: state.creds,
      keys: makeCacheableSignalKeyStore(state.keys, baileysLogger),
    },
    printQRInTerminal: false,
    syncFullHistory: false,
    markOnlineOnConnect: false,
    generateHighQualityLinkPreview: false,
    getMessage: async () => ({ conversation: '' }),
  })

  session.sock = sock
  sock.ev.on('creds.update', saveCreds)

  sock.ev.on('connection.update', async (update) => {
    const { connection, lastDisconnect, qr } = update

    if (qr) {
      try {
        const qrDataUrl = await QRCode.toDataURL(qr, { width: 256, margin: 2 })
        updateStatus(tenantId, 'qr_pending', { qrDataUrl })
        logger.info({ tenantId }, 'QR generated — waiting for scan')
      } catch (err) {
        logger.error({ err, tenantId }, 'failed to encode QR')
      }
    }

    if (connection === 'open') {
      const phone = sock.user?.id?.split(':')[0]?.replace(/\D/g, '') || null
      updateStatus(tenantId, 'connected', { phone, qrDataUrl: null, reason: null })
      logger.info({ tenantId, phone }, 'baileys connected')
    }

    if (connection === 'close') {
      const code = lastDisconnect?.error?.output?.statusCode
      const reason = lastDisconnect?.error?.message || `code=${code}`
      const loggedOut = code === DisconnectReason.loggedOut

      logger.warn({ tenantId, code, reason }, 'baileys connection closed')

      if (loggedOut) {
        updateStatus(tenantId, 'disconnected', { reason: 'logged_out', phone: null })
        // Auth invalid; drop it so a fresh QR is required next connect.
        try {
          rmSync(session.authDir, { recursive: true, force: true })
        } catch (err) {
          logger.warn({ err, tenantId }, 'failed to clear authDir after logout')
        }
        dropSession(tenantId)
      } else if (!session.stopReconnect) {
        updateStatus(tenantId, 'connecting', { reason })
        scheduleReconnect(tenantId, logger)
      } else {
        updateStatus(tenantId, 'disconnected', { reason: 'user_disconnect' })
      }
    }
  })

  // Message listener — forwards both directions to AtendIA.
  //   * fromMe=false → customer wrote to us. Goes to /inbound.
  //   * fromMe=true  → operator wrote from their own phone / WhatsApp Web.
  //                    Echo to /outbound-echo so AtendIA mirrors the chat.
  //                    (Without this echo, sending from the phone bypasses
  //                    AtendIA entirely and the dashboard goes silent.)
  sock.ev.on('messages.upsert', async ({ messages, type }) => {
    if (type !== 'notify') return
    for (const msg of messages) {
      if (!msg.message) continue
      const text = extractMessageText(msg.message)
      if (!text) {
        logger.debug(
          { tenantId, messageId: msg.key?.id, keys: Object.keys(msg.message || {}) },
          'skipping message with no extractable text',
        )
        continue
      }

      const fromJid = msg.key.remoteJid || ''
      if (fromJid.includes('@g.us') || fromJid.includes('@broadcast')) continue
      // LID-aware peer resolution: WhatsApp sometimes addresses by
      // Linked Identity instead of phone — resolveLid falls back to the
      // raw digits when no mapping is cached.
      const peerPhone = resolveLid(fromJid, lidCache)
      if (!peerPhone || peerPhone.length < 8) continue

      const ts = msg.messageTimestamp ? Number(msg.messageTimestamp) * 1000 : Date.now()
      const isOutbound = !!msg.key?.fromMe

      // Visible breadcrumb on every routed message so we can confirm the
      // sidecar is actually capturing fromMe events when debugging.
      logger.info(
        { tenantId, peerPhone, isOutbound, messageId: msg.key?.id },
        isOutbound ? 'forwarding outbound echo' : 'forwarding inbound',
      )

      try {
        if (isOutbound) {
          await postOutboundEcho({
            tenant_id: tenantId,
            to_phone: peerPhone,
            text,
            ts,
            message_id: msg.key.id || null,
          })
        } else {
          await postInbound({
            tenant_id: tenantId,
            from_phone: peerPhone,
            text,
            ts,
            message_id: msg.key.id || null,
          })
        }
      } catch (err) {
        logger.error(
          { err, tenantId, peerPhone, isOutbound },
          'failed to forward message',
        )
      }
    }
  })

  return statusOf(session)
}

export async function stopSession(tenantId, logger) {
  const session = sessionFor(tenantId)
  session.stopReconnect = true
  clearReconnect(tenantId)
  if (session.sock) {
    try {
      await session.sock.logout()
    } catch (err) {
      logger.warn({ err, tenantId }, 'logout error (ignored)')
    }
    session.sock = null
  }
  updateStatus(tenantId, 'disconnected', { reason: 'user_disconnect', phone: null, qrDataUrl: null })
  try {
    rmSync(session.authDir, { recursive: true, force: true })
  } catch (err) {
    logger.warn({ err, tenantId }, 'failed to clear authDir on disconnect')
  }
  dropSession(tenantId)
  return { status: 'disconnected' }
}

export function getSession(tenantId) {
  return statusOf(sessionFor(tenantId))
}

/**
 * Send a text message via this tenant's connected Baileys socket.
 * Includes a short presence/typing dance to feel human; the typing
 * delay is capped so the AtendIA runner doesn't perceive latency.
 */
export async function sendText(tenantId, toPhone, text, logger) {
  const session = sessionFor(tenantId)
  if (session.status !== 'connected' || !session.sock) {
    throw new Error(`session_not_connected (status=${session.status})`)
  }
  const cleaned = String(toPhone).replace(/\D/g, '')
  if (cleaned.length < 8) throw new Error('invalid_phone')
  const jid = `${cleaned}@s.whatsapp.net`
  const sock = session.sock

  try {
    await sock.presenceSubscribe(jid)
    await sock.sendPresenceUpdate('composing', jid)
    const typingMs = Math.min(Math.max(text.length * 20, 400), 1500)
    await new Promise((r) => setTimeout(r, typingMs))
    await sock.sendPresenceUpdate('paused', jid)
  } catch (err) {
    logger?.warn?.({ err, tenantId }, 'presence dance failed (continuing)')
  }

  const result = await sock.sendMessage(jid, { text })
  return {
    message_id: result?.key?.id || null,
    sent_at: new Date().toISOString(),
  }
}

function statusOf(session) {
  return {
    status: session.status,
    phone: session.phone,
    last_status_at: session.statusAt.toISOString(),
    reason: session.statusReason,
  }
}
