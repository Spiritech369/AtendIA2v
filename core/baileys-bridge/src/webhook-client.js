// Inbound webhook client — pushes messages from Baileys to the AtendIA
// backend at /api/v1/internal/baileys/inbound with retry + backoff.

const API_BASE = process.env.ATENDIA_API_BASE || 'http://atendia-backend:8001'
const INTERNAL_TOKEN = process.env.INTERNAL_TOKEN || ''
const TIMEOUT_MS = 5000

/**
 * Post a single inbound message. Retries up to 3 times with exponential
 * backoff. Throws after exhaustion so the caller can log.
 */
export async function postInbound(payload) {
  const url = `${API_BASE}/api/v1/internal/baileys/inbound`
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
    // exponential backoff: 200ms, 800ms, 3200ms
    if (attempt < 3) {
      await new Promise((r) => setTimeout(r, 200 * 4 ** (attempt - 1)))
    }
  }
  throw lastErr
}
