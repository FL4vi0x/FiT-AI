import { describe, expect, it, vi } from 'vitest'
import { createHandler, LOCAL_VEHICLE_PREFIX } from '../vite.local-assets.mjs'

// The dev-only route that serves the local preview assets: what it must REFUSE. (That it serves a real file on loopback is
// covered in the browser by e2e/model-preview.mjs.)
function call(url: string, opts: { addr?: string; host?: string; method?: string; config?: Record<string, string> } = {}) {
  const headers: Record<string, string> = {}
  const res = { statusCode: 0, setHeader: (k: string, v: string) => void (headers[k.toLowerCase()] = v), end: vi.fn() }
  const next = vi.fn()
  const handler = createHandler(() => opts.config ?? { 'model-c': 'C:/nowhere/model.glb' })
  handler(
    { url, method: opts.method ?? 'GET', socket: { remoteAddress: opts.addr ?? '127.0.0.1' }, headers: { host: opts.host ?? '127.0.0.1:5173' } } as never,
    res as never,
    next,
  )
  return { res, next, headers }
}

describe('local vehicle asset route', () => {
  it('ignores every other URL', () => {
    const { next, res } = call('/api/v1/chat')
    expect(next).toHaveBeenCalled()
    expect(res.end).not.toHaveBeenCalled()
  })

  it('refuses a non-loopback socket', () => {
    expect(call(`${LOCAL_VEHICLE_PREFIX}model-c.glb`, { addr: '192.168.0.9' }).res.statusCode).toBe(403)
  })

  it('refuses a non-loopback Host header (DNS rebinding)', () => {
    expect(call(`${LOCAL_VEHICLE_PREFIX}model-c.glb`, { host: 'evil.example' }).res.statusCode).toBe(403)
    expect(call(`${LOCAL_VEHICLE_PREFIX}model-c.glb`, { host: '127.0.0.1.evil.example' }).res.statusCode).toBe(403)
  })

  it('accepts the loopback names', () => {
    for (const h of ['127.0.0.1:5173', 'localhost:5180', '[::1]:5173']) expect(call(`${LOCAL_VEHICLE_PREFIX}model-c.glb`, { host: h }).res.statusCode).not.toBe(403)
  })

  it('only GET and HEAD', () => {
    expect(call(`${LOCAL_VEHICLE_PREFIX}model-c.glb`, { method: 'POST' }).res.statusCode).toBe(405)
  })

  it('never builds a path from the URL: odd ids are 404', () => {
    for (const id of ['..%2Fpackage', '../package', 'a/b', 'MODEL-C', '', 'x'.repeat(40)]) expect(call(`${LOCAL_VEHICLE_PREFIX}${id}.glb`).res.statusCode).toBe(404)
  })

  it('404 for an id that is not in the local config, or whose file is missing (no cache, no content)', () => {
    const unknown = call(`${LOCAL_VEHICLE_PREFIX}model-z.glb`)
    expect(unknown.res.statusCode).toBe(404)
    expect(unknown.headers['cache-control']).toBe('no-store')
    expect(call(`${LOCAL_VEHICLE_PREFIX}model-c.glb`).res.statusCode).toBe(404) // listed, but C:/nowhere does not exist
  })

  it('refuses a config entry that is not a .glb', () => {
    expect(call(`${LOCAL_VEHICLE_PREFIX}model-c.glb`, { config: { 'model-c': 'C:/Windows/System32/config/SAM' } }).res.statusCode).toBe(404)
  })

  it('survives a missing or broken config file', () => {
    const res = { statusCode: 0, setHeader: vi.fn(), end: vi.fn() }
    createHandler(() => {
      throw new Error('no file')
    })({ url: `${LOCAL_VEHICLE_PREFIX}model-c.glb`, method: 'GET', socket: { remoteAddress: '127.0.0.1' }, headers: { host: '127.0.0.1:5173' } } as never, res as never, vi.fn())
    expect(res.statusCode).toBe(404)
  })
})
