import assert from 'node:assert/strict'
import { mkdtemp, readdir, rm } from 'node:fs/promises'
import { createServer } from 'node:http'
import os from 'node:os'
import path from 'node:path'
import { afterEach, beforeEach, test } from 'node:test'

import { drainWebhookRetryQueue, postInbound } from '../src/webhook-client.js'

let retryDir
let server

function listen(server) {
  return new Promise((resolve) => {
    server.listen(0, '127.0.0.1', () => resolve(server.address()))
  })
}

function close(server) {
  return new Promise((resolve, reject) => {
    server.close((err) => (err ? reject(err) : resolve()))
  })
}

beforeEach(async () => {
  retryDir = await mkdtemp(path.join(os.tmpdir(), 'atendia-webhook-retry-'))
  process.env.WEBHOOK_RETRY_DIR = retryDir
  process.env.WEBHOOK_TIMEOUT_MS = '50'
  process.env.WEBHOOK_INLINE_ATTEMPTS = '1'
})

afterEach(async () => {
  delete process.env.ATENDIA_API_BASE
  delete process.env.WEBHOOK_RETRY_DIR
  delete process.env.WEBHOOK_TIMEOUT_MS
  delete process.env.WEBHOOK_INLINE_ATTEMPTS
  if (server) {
    await close(server)
    server = null
  }
  if (retryDir) {
    await rm(retryDir, { recursive: true, force: true })
    retryDir = null
  }
})

test('postInbound stores a retry job when backend is unavailable', async () => {
  process.env.ATENDIA_API_BASE = 'http://127.0.0.1:9'

  await postInbound({
    tenant_id: 'tenant-1',
    from_phone: '5218123456789',
    text: 'hola',
    ts: Date.now(),
    message_id: 'msg-1',
  })

  const files = await readdir(retryDir)
  assert.equal(files.length, 1)
  assert.match(files[0], /\.json$/)
})

test('drainWebhookRetryQueue delivers queued inbound and removes the job', async () => {
  let acceptRequests = false
  const received = []
  server = createServer((req, res) => {
    let body = ''
    req.on('data', (chunk) => {
      body += chunk
    })
    req.on('end', () => {
      if (!acceptRequests) {
        res.writeHead(503)
        res.end('starting')
        return
      }
      received.push({ url: req.url, body: JSON.parse(body) })
      res.writeHead(200, { 'content-type': 'application/json' })
      res.end('{}')
    })
  })
  const address = await listen(server)
  process.env.ATENDIA_API_BASE = `http://127.0.0.1:${address.port}`

  await postInbound({
    tenant_id: 'tenant-1',
    from_phone: '5218123456789',
    text: 'hola',
    ts: Date.now(),
    message_id: 'msg-2',
  })
  assert.equal((await readdir(retryDir)).length, 1)

  acceptRequests = true
  const result = await drainWebhookRetryQueue({ info() {}, warn() {}, error() {} })

  assert.deepEqual(result, { attempted: 1, delivered: 1, failed: 0 })
  assert.equal((await readdir(retryDir)).length, 0)
  assert.equal(received.length, 1)
  assert.equal(received[0].url, '/api/v1/internal/baileys/inbound')
  assert.equal(received[0].body.message_id, 'msg-2')
})
