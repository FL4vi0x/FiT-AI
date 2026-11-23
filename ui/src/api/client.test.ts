import { describe, expect, it, vi } from 'vitest'
import { ApiError, NetworkError, createApi } from './client'

function json(status: number, body: unknown, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json', ...headers } })
}

describe('api client', () => {
  it('GETs the three read endpoints with no credentials, no cache and no referrer', async () => {
    const fetchImpl = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => json(200, { status: 'ok', service: 'fit-ai-core', version: '0.1.0' }))
    const api = createApi({ fetchImpl })
    await api.health()
    await api.status()
    await api.telemetry()
    const urls = fetchImpl.mock.calls.map((c) => c[0])
    expect(urls).toEqual(['/health', '/api/v1/vehicle/status', '/api/v1/vehicle/telemetry'])
    const init = fetchImpl.mock.calls[0]![1] as RequestInit
    expect(init.method).toBe('GET')
    expect(init.credentials).toBe('omit')
    expect(init.cache).toBe('no-store')
    expect(init.referrerPolicy).toBe('no-referrer')
  })

  it('POSTs the chat request as JSON and returns the typed body', async () => {
    const fetchImpl = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => json(200, { answer: 'oi', used_tools: [] }))
    const api = createApi({ fetchImpl })
    const res = await api.chat({ message: 'oi', conversation_id: null })
    expect(res.answer).toBe('oi')
    const [url, init] = fetchImpl.mock.calls[0] as [string, RequestInit]
    expect(url).toBe('/api/v1/chat')
    expect(init.method).toBe('POST')
    expect((init.headers as Record<string, string>)['Content-Type']).toBe('application/json')
    expect(JSON.parse(init.body as string)).toEqual({ message: 'oi', conversation_id: null })
  })

  it('turns the Core error body into an ApiError with its stable code, request id and Retry-After', async () => {
    const fetchImpl = vi.fn(async () => json(429, { error: { code: 'service_busy', message: 'busy' }, request_id: 'abc123' }, { 'Retry-After': '10' }))
    const err = await createApi({ fetchImpl }).chat({ message: 'x' }).catch((e) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect(err).toMatchObject({ status: 429, code: 'service_busy', requestId: 'abc123', retryAfterS: 10 })
  })

  it('keeps a failure controlled when the body is not the Core error shape (proxy page, FastAPI detail)', async () => {
    const detail = await createApi({ fetchImpl: async () => json(404, { detail: 'Not Found' }) }).health().catch((e) => e)
    expect(detail).toMatchObject({ status: 404, code: 'http_404' })
    const html = await createApi({ fetchImpl: async () => new Response('<html>bad gateway</html>', { status: 502 }) }).health().catch((e) => e)
    expect(html).toMatchObject({ status: 502, code: 'http_502' })
  })

  it('rejects a 200 whose body is not an object', async () => {
    const err = await createApi({ fetchImpl: async () => new Response('null', { status: 200 }) }).health().catch((e) => e)
    expect(err).toMatchObject({ code: 'invalid_response' })
  })

  it('reports an unreachable Core as NetworkError(offline)', async () => {
    const err = await createApi({ fetchImpl: async () => Promise.reject(new TypeError('failed to fetch')) }).health().catch((e) => e)
    expect(err).toBeInstanceOf(NetworkError)
    expect(err.kind).toBe('offline')
  })

  it('reports a slow Core as NetworkError(timeout) and aborts the request', async () => {
    let aborted = false
    const fetchImpl = (_: RequestInfo | URL, init?: RequestInit) =>
      new Promise<Response>((_, reject) => {
        init?.signal?.addEventListener('abort', () => {
          aborted = true
          reject(new DOMException('aborted', 'AbortError'))
        })
      })
    const err = await createApi({ fetchImpl: fetchImpl as typeof fetch, timeoutMs: 30 }).telemetry().catch((e) => e)
    expect(err).toBeInstanceOf(NetworkError)
    expect(err.kind).toBe('timeout')
    expect(aborted).toBe(true)
  })
})
