import { describe, expect, it } from 'vitest'
import type { ChatResponse, StatusResponse, TelemetryResponse } from '../api/types'
import { derive, initialState, reducer, type Action, type AppState } from './store'

const T0 = 1_700_000_000_000
const reading: TelemetryResponse = { rpm: 820, speed_kmh: 0, coolant_temp_c: 90, missing: [], source: 'octave', simulated: true, timestamp: new Date(T0).toISOString() }
const status: StatusResponse = { available: true, state: 'connected', source: 'octave', simulated: true, protocol_version: 3, octave_version: '0.9.6', detail: null }
const chat = (over: Partial<ChatResponse> = {}): ChatResponse => ({
  conversation_id: 'c0ffee00c0ffee00c0ffee00c0ffee00',
  request_id: 'r1',
  answer: 'No simulador, o motor está a 820 rpm.',
  model: 'qwen3:4b',
  answer_origin: 'llm',
  used_tools: ['get_vehicle_telemetry'],
  fallback_used: false,
  data_source: 'octave',
  simulated: true,
  availability: 'ok',
  model_status: 'ok',
  memory_saved: false,
  history_saved: true,
  replayed: false,
  latency_ms: 4620,
  ...over,
})
const run = (actions: Action[], from: AppState = initialState()) => actions.reduce(reducer, from)
const online: Action[] = [{ type: 'core/online', at: T0, version: '0.1.0', latencyMs: 12 }, { type: 'octave/status', at: T0, status }]

describe('visual mode derivation', () => {
  it('starts idle and quiet: nothing projected', () => {
    const d = derive(run(online))
    expect(d).toMatchObject({ mode: 'idle', core: 'idle', panels: [], zones: [] })
  })

  it('stays clean after the boot checks: the link is not announced when it is fine', () => {
    expect(derive(run(online))).toMatchObject({ mode: 'idle', panels: [], zones: [], faulty: [] })
  })

  it('shows only the system readout when the user asked about the link (a status-tool answer)', () => {
    const d = derive(run([...online, { type: 'glance/show', at: T0 }]))
    expect(d).toMatchObject({ mode: 'presenting', panels: ['system'], zones: ['cabin'] })
  })

  it('scans while telemetry is being read: all zones lit, no panel yet', () => {
    const d = derive(run([...online, { type: 'telemetry/loading', at: T0, reason: 'manual' }]))
    expect(d).toMatchObject({ mode: 'scanning', core: 'scanning', panels: [] })
    expect(d.zones).toHaveLength(4)
  })

  it('thinks while the chat is busy, and hides previous panels', () => {
    const s = run([...online, { type: 'telemetry/ok', at: T0, reading, reason: 'manual' }, { type: 'chat/send', at: T0, id: 'u1', text: 'oi' }])
    expect(derive(s)).toMatchObject({ mode: 'thinking', core: 'thinking', panels: [] })
  })

  it('presents the three readings (and lights only their regions) when a reading is on screen', () => {
    const d = derive(run([...online, { type: 'telemetry/ok', at: T0, reading, reason: 'manual' }]))
    expect(d.mode).toBe('presenting')
    expect(d.panels).toEqual(['rpm', 'speed', 'temp'])
    expect(d.zones).toEqual(['powertrain', 'cooling', 'motion'])
  })

  it('says "responding" for a moment after an answer, then goes back to idle', () => {
    const answered = run([...online, { type: 'chat/send', at: T0, id: 'u1', text: 'o que é óleo?' }, { type: 'chat/done', at: T0, id: 'a1', response: chat({ used_tools: [], answer_origin: 'llm', availability: 'not_requested', simulated: null }) }])
    expect(derive(answered).core).toBe('responding')
    expect(derive(reducer(answered, { type: 'chat/responding-end' })).core).toBe('idle')
  })

  it('shows an unavailable state (system callout only, faulty cabin zone) when there is no reading', () => {
    const d = derive(run([...online, { type: 'telemetry/fail', at: T0, code: 'octave_unavailable', message: 'x', reason: 'manual' }]))
    expect(d).toMatchObject({ mode: 'unavailable', panels: ['system'], faulty: ['cabin'], zones: [] })
  })

  it('is offline whenever the Core is unreachable, whatever else was going on', () => {
    const s = run([...online, { type: 'telemetry/ok', at: T0, reading, reason: 'manual' }, { type: 'core/offline', at: T0, reason: 'x' }])
    expect(derive(s)).toMatchObject({ mode: 'offline', core: 'offline', panels: [], zones: [] })
  })
})

describe('reducer', () => {
  it('forgets the reading, the glance, live mode and the Ollama state when the Core goes offline', () => {
    let s = run([...online, { type: 'chat/send', at: T0, id: 'u1', text: 'q' }, { type: 'chat/done', at: T0, id: 'a1', response: chat() }, { type: 'telemetry/ok', at: T0, reading, reason: 'chat' }, { type: 'live/set', value: true }])
    expect(s.ollama.status).toBe('online')
    s = reducer(s, { type: 'core/offline', at: T0, reason: 'x' })
    expect(s.telemetry).toEqual({ phase: 'idle' })
    expect(s.live).toBe(false)
    expect(s.ollama.status).toBe('unknown')
    expect(s.octave.status).toBe('unknown')
    expect(s.chat.busy).toBe(false)
  })

  it('infers Ollama only from what chat reports: ok, unavailable, timeout; not_used teaches nothing', () => {
    const s0 = run(online)
    expect(run([{ type: 'chat/done', at: T0, id: 'a', response: chat({ model_status: 'ok' }) }], s0).ollama.status).toBe('online')
    expect(run([{ type: 'chat/done', at: T0, id: 'a', response: chat({ model_status: 'unavailable' }) }], s0).ollama.status).toBe('offline')
    expect(run([{ type: 'chat/done', at: T0, id: 'a', response: chat({ model_status: 'not_found' }) }], s0).ollama.status).toBe('offline')
    expect(run([{ type: 'chat/done', at: T0, id: 'a', response: chat({ model_status: 'timeout' }) }], s0).ollama.status).toBe('degraded')
    const known = run([{ type: 'chat/done', at: T0, id: 'a', response: chat({ model_status: 'ok' }) }], s0)
    expect(run([{ type: 'chat/done', at: T0, id: 'b', response: chat({ model_status: 'not_used' }) }], known).ollama.status).toBe('online')
  })

  it('marks Ollama from error codes of a failed chat', () => {
    const s = run([...online, { type: 'chat/failed', at: T0, id: 'e', code: 'model_unavailable', message: 'x', requestId: null }])
    expect(s.ollama.status).toBe('offline')
    expect(s.chat.busy).toBe(false)
    expect(s.chat.entries.at(-1)).toMatchObject({ role: 'error', code: 'model_unavailable' })
  })

  it('"new conversation" forgets the conversation id and the entries, but not while the assistant is busy', () => {
    const talked = run([...online, { type: 'chat/send', at: T0, id: 'u', text: 'q' }, { type: 'chat/done', at: T0, id: 'a', response: chat() }])
    const fresh = reducer(talked, { type: 'chat/reset', at: T0 })
    expect(fresh.chat.entries).toEqual([])
    expect(fresh.chat.conversationId).toBeNull()
    const busy = reducer(talked, { type: 'chat/send', at: T0, id: 'u2', text: 'outra' })
    expect(reducer(busy, { type: 'chat/reset', at: T0 }).chat.entries).toHaveLength(3)
  })

  it('keeps the conversation id returned by the Core', () => {
    const s = run([...online, { type: 'chat/send', at: T0, id: 'u', text: 'q' }, { type: 'chat/done', at: T0, id: 'a', response: chat() }])
    expect(s.chat.conversationId).toBe('c0ffee00c0ffee00c0ffee00c0ffee00')
    expect(s.chat.entries.map((e) => e.role)).toEqual(['user', 'assistant'])
  })

  it('a status-only answer glances at the system callout instead of projecting readings', () => {
    const d = derive(run([...online, { type: 'chat/send', at: T0, id: 'u', text: 'conexão?' }, { type: 'chat/done', at: T0, id: 'a', response: chat({ used_tools: ['get_vehicle_status'], answer_origin: 'deterministic' }) }]))
    expect(d.panels).toEqual(['system'])
  })

  it('describes the OCTAVE link: connected, degraded (no vehicle) and unreachable', () => {
    const at = (st: Partial<StatusResponse>) => run([{ type: 'octave/status', at: T0, status: { ...status, ...st } }]).octave.status
    expect(at({})).toBe('connected')
    expect(at({ state: 'vehicle_link_down' })).toBe('degraded')
    expect(at({ available: false, state: 'octave_unavailable' })).toBe('unreachable')
  })

  it('the live refresh is silent (no feed line) but updates the reading', () => {
    const base = run([...online, { type: 'telemetry/ok', at: T0, reading, reason: 'manual' }])
    const n = base.feed.length
    const live = reducer(base, { type: 'telemetry/ok', at: T0 + 2000, reading: { ...reading, rpm: 900 }, reason: 'live' })
    expect(live.feed.length).toBe(n)
    expect(live.telemetry.phase === 'ready' && live.telemetry.reading.rpm).toBe(900)
  })

  it('logs only real changes and caps the feed', () => {
    let s = run(online)
    const n = s.feed.length
    s = reducer(s, { type: 'octave/status', at: T0 + 1, status }) // same status again
    s = reducer(s, { type: 'core/online', at: T0 + 2, version: '0.1.0', latencyMs: 9 })
    expect(s.feed.length).toBe(n)
    for (let i = 0; i < 80; i++) s = reducer(s, { type: 'telemetry/loading', at: T0 + i, reason: 'manual' })
    expect(s.feed.length).toBeLessThanOrEqual(40)
  })

  it('a missing field is reported as missing in the feed, never as zero', () => {
    const s = run([...online, { type: 'telemetry/ok', at: T0, reading: { ...reading, speed_kmh: null, coolant_temp_c: null, missing: ['speed_kmh', 'coolant_temp_c'] }, reason: 'manual' }])
    const line = s.feed.at(-1)!
    expect(line.text).toContain('— km/h')
    expect(line.text).toContain('sem speed_kmh')
    expect(line.level).toBe('warn')
  })
})
