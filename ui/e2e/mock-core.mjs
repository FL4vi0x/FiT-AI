// A stand-in for the Fit AI Core that obeys the SAME HTTP contract (fit_ai/api/routes.py, conversation/models.py), used only
// to exercise the UI deterministically (every state, including failures). It is a QA tool: it is never bundled into the UI,
// and it binds to loopback only. Scenarios are switched with POST /__mock/config (the browser never calls that path).
import http from 'node:http'

const reading = () => ({
  rpm: 820,
  speed_kmh: 0,
  coolant_temp_c: 90,
  missing: [],
  source: 'octave',
  simulated: true,
  timestamp: new Date().toISOString(),
})

const defaults = () => ({
  latency: { telemetry: 0, chat: 700, status: 0 },
  health: { ok: true },
  status: { available: true, state: 'connected', source: 'octave', simulated: true, protocol_version: 3, octave_version: '0.9.6', detail: null },
  telemetry: { kind: 'ok' }, // 'ok' | 'partial' | 'error'
  chat: { kind: 'auto' }, // 'auto' | 'fallback' | 'error' | 'no-tools'
  llm: { state: 'available' }, // 'available' | 'model_not_installed' | 'unavailable' | 'unverified' | 'not_configured'
})

export function startMockCore({ port = 8010 } = {}) {
  let cfg = defaults()
  // `reset` restores the defaults first and THEN applies the rest of the patch; `latency` merges key by key.
  const apply = (patch) => {
    const { reset, ...rest } = patch ?? {}
    const base = reset ? defaults() : cfg
    cfg = { ...base, ...rest, latency: { ...base.latency, ...(rest.latency ?? {}) } }
  }
  const calls = []
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
  const send = (res, status, body, headers = {}) => {
    res.writeHead(status, { 'Content-Type': 'application/json', ...headers })
    res.end(JSON.stringify(body))
  }

  const chatFor = (message) => {
    const q = message.toLowerCase()
    const base = {
      conversation_id: 'c0ffee00c0ffee00c0ffee00c0ffee00',
      request_id: Math.random().toString(16).slice(2).padEnd(32, '0'),
      model: 'qwen3:4b-instruct-2507-q4_K_M',
      memory_saved: false,
      history_saved: true,
      replayed: false,
      latency_ms: 4620,
    }
    if (cfg.chat.kind === 'no-tools') {
      return { ...base, answer: 'Troca de óleo é a substituição periódica do lubrificante do motor.', answer_origin: 'llm', used_tools: [], fallback_used: false, data_source: null, simulated: null, availability: 'not_requested', model_status: 'ok' }
    }
    if (/conex|status|ligad/.test(q)) {
      return { ...base, answer: 'A fonte de dados está conectada e funciona em modo simulado (os dados vêm de um simulador).', answer_origin: 'deterministic', used_tools: ['get_vehicle_status'], fallback_used: true, data_source: 'octave', simulated: true, availability: 'ok', model_status: 'not_used', latency_ms: 38 }
    }
    const partial = cfg.telemetry.kind === 'partial'
    if (cfg.chat.kind === 'fallback') {
      return { ...base, answer: 'Dados simulados (não são do carro real): rotação 820 rpm; velocidade 0 km/h.', answer_origin: 'fallback', used_tools: ['get_vehicle_telemetry'], fallback_used: true, data_source: 'octave', simulated: true, availability: partial ? 'partial' : 'ok', model_status: 'ok', latency_ms: 31200 }
    }
    return {
      ...base,
      answer: partial ? 'No simulador, o motor está a 820 rpm. A velocidade e a temperatura não estão disponíveis.' : 'No simulador, o motor está a 820 rpm.',
      answer_origin: 'llm',
      used_tools: ['get_vehicle_telemetry'],
      fallback_used: false,
      data_source: 'octave',
      simulated: true,
      availability: cfg.telemetry.kind === 'error' ? 'unavailable' : partial ? 'partial' : 'ok',
      model_status: 'ok',
    }
  }

  const server = http.createServer(async (req, res) => {
    const url = new URL(req.url ?? '/', 'http://127.0.0.1')
    const chunks = []
    for await (const c of req) chunks.push(c)
    const raw = Buffer.concat(chunks).toString('utf8')
    const body = raw ? JSON.parse(raw) : null

    if (url.pathname === '/__mock/config' && req.method === 'POST') {
      apply(body)
      return send(res, 200, { ok: true })
    }
    if (url.pathname === '/__mock/calls') return send(res, 200, calls)
    calls.push({ method: req.method, path: url.pathname, origin: req.headers.origin ?? null, host: req.headers.host ?? null, body })

    if (url.pathname === '/health') {
      if (!cfg.health.ok) return send(res, 500, { error: { code: 'internal_error', message: 'x' } })
      return send(res, 200, { status: 'ok', service: 'fit-ai-core', version: '0.1.0' })
    }
    if (url.pathname === '/api/v1/llm/status') {
      return send(res, 200, { state: cfg.llm.state, model: 'qwen3:4b-instruct-2507-q4_K_M', checked_at: new Date().toISOString() })
    }
    if (url.pathname === '/api/v1/voice/status') {
      return send(res, 200, { state: 'available', language: 'pt', max_audio_s: 30, sample_rate: 16000, hint: null })
    }
    if (url.pathname === '/api/v1/vehicle/status') {
      await sleep(cfg.latency.status)
      return send(res, 200, cfg.status)
    }
    if (url.pathname === '/api/v1/vehicle/telemetry') {
      await sleep(cfg.latency.telemetry)
      if (cfg.telemetry.kind === 'error') {
        const e = cfg.telemetry
        return send(res, e.status ?? 503, { error: { code: e.code ?? 'octave_unavailable', message: e.message ?? 'OCTAVE unavailable' } })
      }
      const r = reading()
      if (cfg.telemetry.kind === 'partial') return send(res, 200, { ...r, speed_kmh: null, coolant_temp_c: null, missing: ['speed_kmh', 'coolant_temp_c'] })
      return send(res, 200, r)
    }
    if (url.pathname === '/api/v1/chat') {
      if (req.method !== 'POST') return send(res, 405, { error: { code: 'method_not_allowed', message: 'Only POST is allowed on this route.' } })
      await sleep(cfg.latency.chat)
      if (cfg.chat.kind === 'error') {
        const e = cfg.chat
        return send(res, e.status ?? 503, { error: { code: e.code ?? 'model_unavailable', message: 'x' }, request_id: 'deadbeefdeadbeefdeadbeefdeadbeef' }, e.status === 429 ? { 'Retry-After': '10' } : {})
      }
      return send(res, 200, chatFor(String(body?.message ?? '')))
    }
    return send(res, 404, { detail: 'Not Found' })
  })

  return new Promise((resolve) => {
    server.listen(port, '127.0.0.1', () =>
      resolve({
        port,
        calls,
        configure: apply,
        close: () => new Promise((r) => (server.closeAllConnections?.(), server.close(() => r()))),
      }),
    )
  })
}

if (import.meta.url === `file://${process.argv[1].replaceAll('\\', '/')}` || process.argv[1]?.endsWith('mock-core.mjs')) {
  const port = Number(process.env.MOCK_CORE_PORT ?? 8010)
  startMockCore({ port }).then(() => console.log(`mock Fit AI Core on http://127.0.0.1:${port}`))
}
