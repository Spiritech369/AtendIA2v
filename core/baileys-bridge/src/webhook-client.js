// Webhook client — pushes messages from Baileys to the AtendIA backend.
// `postInbound` is for customer → us. `postOutboundEcho` is for messages
// the operator sent from their own phone / WhatsApp Web (fromMe=true) so
// AtendIA can mirror them into the conversation.

const API_BASE = process.env.ATENDIA_API_BASE || 'http://atendia-backend:8001'
const INTERNAL_TOKEN = process.env.INTERNAL_TOKEN || ''
const TIMEOUT_MS = 5000

async function postWithRetry(url, payload) {
  let lastErr
  for (let attempt = 1; attempt <= 3; attempt++) {
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), TIMEOUT_MS)
    try {
      const res = await fetch(url, {
        method: 'POST',
        headers: {
          'content-type': 'application/json',
          'x-internal-token': INTERNAL_TOKEN,
        },
        body: JSON.stringify(payload),
        signal: controller.signal,
      })
      clearTimeout(timer)
      if (res.ok) return
      lastErr = new Error(`backend responded ${res.status}`)
    } catch (err) {
      clearTimeout(timer)
      lastErr = err
    }
    if (attempt < 3) {
      await new Promise((r) => setTimeout(r, 200 * 4 ** (attempt - 1)))
    }
  }
  throw lastErr
}

export async function postInbound(payload) {
  await postWithRetry(`${API_BASE}/api/v1/internal/baileys/inbound`, payload)
}

export async function postOutboundEcho(payload) {
  await postWithRetry(`${API_BASE}/api/v1/internal/baileys/outbound-echo`, payload)
}
