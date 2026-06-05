// Webhook client: pushes messages from Baileys to the AtendIA backend.
// `postInbound` is for customer -> us. `postOutboundEcho` is for messages
// the operator sent from their own phone / WhatsApp Web (fromMe=true) so
// AtendIA can mirror them into the conversation.

import { randomUUID } from 'node:crypto'
import { mkdir, readdir, readFile, rename, rm, writeFile } from 'node:fs/promises'
import path from 'node:path'

const DEFAULT_API_BASE = 'http://atendia-backend:8001'
const DEFAULT_TIMEOUT_MS = 5000
const DEFAULT_INLINE_ATTEMPTS = 3
const DEFAULT_DRAIN_INTERVAL_MS = 3000
const MAX_RETRY_DELAY_MS = 60_000

let retryTimer = null
let activeLogger = console

function apiBase() {
  return process.env.ATENDIA_API_BASE || DEFAULT_API_BASE
}

function internalToken() {
  return process.env.INTERNAL_TOKEN || ''
}

function timeoutMs() {
  return Number(process.env.WEBHOOK_TIMEOUT_MS || DEFAULT_TIMEOUT_MS)
}

function inlineAttempts() {
  return Number(process.env.WEBHOOK_INLINE_ATTEMPTS || DEFAULT_INLINE_ATTEMPTS)
}

function drainIntervalMs() {
  return Number(process.env.WEBHOOK_RETRY_INTERVAL_MS || DEFAULT_DRAIN_INTERVAL_MS)
}

function retryDir() {
  return (
    process.env.WEBHOOK_RETRY_DIR ||
    path.join(process.env.AUTH_DIR || '/app/auth_info', '_webhook_retry')
  )
}

function backoffMs(attempts) {
  return Math.min(MAX_RETRY_DELAY_MS, 1000 * 2 ** Math.max(0, attempts - 1))
}

function errorMessage(err) {
  return err?.message || String(err)
}

async function postWithRetry(url, payload) {
  let lastErr
  const attempts = Math.max(1, inlineAttempts())
  for (let attempt = 1; attempt <= attempts; attempt++) {
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), timeoutMs())
    try {
      const res = await fetch(url, {
        method: 'POST',
        headers: {
          'content-type': 'application/json',
          'x-internal-token': internalToken(),
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
    if (attempt < attempts) {
      await new Promise((resolve) => setTimeout(resolve, 200 * 4 ** (attempt - 1)))
    }
  }
  throw lastErr
}

async function enqueueWebhook(kind, url, payload, err = null) {
  const dir = retryDir()
  await mkdir(dir, { recursive: true })
  const id = `${Date.now()}-${randomUUID()}`
  const job = {
    id,
    version: 1,
    kind,
    url,
    payload,
    attempts: 0,
    created_at: new Date().toISOString(),
    last_error: err ? errorMessage(err) : null,
    next_attempt_at: new Date().toISOString(),
  }
  const filePath = path.join(dir, `${id}.json`)
  await writeFile(filePath, JSON.stringify(job, null, 2), 'utf8')
  return { job, filePath }
}

async function deliverOrQueue(kind, pathSuffix, payload) {
  const url = `${apiBase()}${pathSuffix}`
  const { job, filePath } = await enqueueWebhook(kind, url, payload)
  try {
    await postWithRetry(url, payload)
    await rm(filePath, { force: true })
  } catch (err) {
    job.last_error = errorMessage(err)
    job.next_attempt_at = new Date().toISOString()
    await writeRetryJob(filePath, job)
    activeLogger.warn?.({ kind, id: job.id, err }, 'queued webhook for retry')
  }
}

async function writeRetryJob(filePath, job) {
  const tmpPath = `${filePath}.${process.pid}.tmp`
  await writeFile(tmpPath, JSON.stringify(job, null, 2), 'utf8')
  await rename(tmpPath, filePath)
}

export async function drainWebhookRetryQueue(logger = activeLogger) {
  const dir = retryDir()
  let files
  try {
    files = await readdir(dir)
  } catch (err) {
    if (err?.code === 'ENOENT') return { attempted: 0, delivered: 0, failed: 0 }
    throw err
  }

  let attempted = 0
  let delivered = 0
  let failed = 0
  const now = Date.now()

  for (const fileName of files.filter((name) => name.endsWith('.json')).sort()) {
    const filePath = path.join(dir, fileName)
    let job
    try {
      job = JSON.parse(await readFile(filePath, 'utf8'))
    } catch (err) {
      logger.warn?.({ err, fileName }, 'dropping unreadable webhook retry job')
      await rm(filePath, { force: true })
      continue
    }

    const nextAttemptAt = Date.parse(job.next_attempt_at || job.created_at || '')
    if (!Number.isNaN(nextAttemptAt) && nextAttemptAt > now) continue

    attempted += 1
    try {
      await postWithRetry(job.url, job.payload)
      await rm(filePath, { force: true })
      delivered += 1
      logger.info?.({ kind: job.kind, id: job.id, attempts: job.attempts }, 'delivered queued webhook')
    } catch (err) {
      failed += 1
      const attempts = Number(job.attempts || 0) + 1
      job.attempts = attempts
      job.last_error = errorMessage(err)
      job.next_attempt_at = new Date(Date.now() + backoffMs(attempts)).toISOString()
      await writeRetryJob(filePath, job)
      logger.warn?.({ err, kind: job.kind, id: job.id, attempts }, 'queued webhook retry failed')
    }
  }

  return { attempted, delivered, failed }
}

export function startWebhookRetryLoop(logger = console) {
  activeLogger = logger
  if (retryTimer) return retryTimer

  retryTimer = setInterval(() => {
    drainWebhookRetryQueue(logger).catch((err) => {
      logger.error?.({ err }, 'webhook retry queue drain failed')
    })
  }, drainIntervalMs())
  retryTimer.unref?.()

  drainWebhookRetryQueue(logger).catch((err) => {
    logger.error?.({ err }, 'webhook retry queue initial drain failed')
  })

  return retryTimer
}

export async function postInbound(payload) {
  await deliverOrQueue('inbound', '/api/v1/internal/baileys/inbound', payload)
}

export async function postOutboundEcho(payload) {
  await deliverOrQueue('outbound_echo', '/api/v1/internal/baileys/outbound-echo', payload)
}
