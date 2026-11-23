import type { ChatResponse, ModelStatus, StatusResponse, TelemetryResponse } from '../api/types'
import { TOOL_STATUS, TOOL_TELEMETRY } from '../api/types'
import { fmtLatency, fmtNumber } from '../lib/format'
import { ORIGIN_META } from '../lib/labels'
import type { PanelId, ZoneId } from '../lib/vehicleZones'

// ───────────────────────── model ─────────────────────────
export type LinkStatus = 'checking' | 'online' | 'offline'
export interface CoreLink {
  status: LinkStatus
  version: string | null
  latencyMs: number | null
}

export type OctaveStatus = 'unknown' | 'connected' | 'degraded' | 'unreachable'
export interface OctaveLink {
  status: OctaveStatus
  state: string | null
  simulated: boolean | null
  source: string | null
  octaveVersion: string | null
  protocolVersion: number | null
  detail: string | null
}

/** There is no Ollama endpoint in the Core: this link is inferred from what chat reports (`model_status`, error codes). */
export type OllamaStatus = 'unknown' | 'online' | 'degraded' | 'offline'
export interface OllamaLink {
  status: OllamaStatus
  detail: string | null
}

export type ScanReason = 'manual' | 'chat' | 'live'
export interface TelemetryReady {
  phase: 'ready'
  reading: TelemetryResponse
  /** Client clock at the moment the reading arrived. */
  at: number
  reason: ScanReason
}
export type TelemetryView =
  | { phase: 'idle' }
  | { phase: 'loading'; reason: ScanReason }
  | TelemetryReady
  | { phase: 'unavailable'; code: string; message: string; at: number; reason: ScanReason }

export type ChatEntry =
  | { id: string; role: 'user'; text: string; at: number }
  | { id: string; role: 'assistant'; text: string; at: number; meta: ChatResponse }
  | { id: string; role: 'error'; text: string; at: number; code: string; requestId: string | null }

export interface FeedEvent {
  id: number
  at: number
  tag: string
  text: string
  level: 'info' | 'ok' | 'warn' | 'error'
}

export interface AppState {
  core: CoreLink
  octave: OctaveLink
  ollama: OllamaLink
  telemetry: TelemetryView
  /** What is projected on the car besides telemetry: a brief look at the system status. */
  glance: boolean
  chat: { entries: ChatEntry[]; conversationId: string | null; busy: boolean }
  /** Transient: an answer has just arrived (the core shows the "responding" state for a moment). */
  responding: boolean
  live: boolean
  feed: FeedEvent[]
  nextFeedId: number
}

export const FEED_LIMIT = 40

export function initialState(): AppState {
  return {
    core: { status: 'checking', version: null, latencyMs: null },
    octave: { status: 'unknown', state: null, simulated: null, source: null, octaveVersion: null, protocolVersion: null, detail: null },
    ollama: { status: 'unknown', detail: null },
    telemetry: { phase: 'idle' },
    glance: false,
    chat: { entries: [], conversationId: null, busy: false },
    responding: false,
    live: false,
    feed: [],
    nextFeedId: 1,
  }
}

// ───────────────────────── actions ─────────────────────────
export type Action =
  | { type: 'core/online'; at: number; version: string; latencyMs: number }
  | { type: 'core/offline'; at: number; reason: string }
  | { type: 'octave/status'; at: number; status: StatusResponse }
  | { type: 'octave/unknown'; at: number; reason: string }
  | { type: 'chat/send'; at: number; id: string; text: string }
  | { type: 'chat/done'; at: number; id: string; response: ChatResponse }
  | { type: 'chat/failed'; at: number; id: string; code: string; message: string; requestId: string | null }
  | { type: 'chat/responding-end' }
  | { type: 'telemetry/loading'; at: number; reason: ScanReason }
  | { type: 'telemetry/ok'; at: number; reading: TelemetryResponse; reason: ScanReason }
  | { type: 'telemetry/fail'; at: number; code: string; message: string; reason: ScanReason }
  | { type: 'glance/show'; at: number }
  | { type: 'glance/hide' }
  | { type: 'presentation/clear'; at: number }
  | { type: 'chat/reset'; at: number }
  | { type: 'live/set'; value: boolean }

function log(s: AppState, at: number, tag: string, text: string, level: FeedEvent['level'] = 'info'): AppState {
  const ev: FeedEvent = { id: s.nextFeedId, at, tag, text, level }
  return { ...s, feed: [...s.feed, ev].slice(-FEED_LIMIT), nextFeedId: s.nextFeedId + 1 }
}

function ollamaFromModelStatus(prev: OllamaLink, status: ModelStatus): OllamaLink {
  switch (status) {
    case 'ok':
      return { status: 'online', detail: null }
    case 'unavailable':
      return { status: 'offline', detail: 'modelo indisponível' }
    case 'not_found':
      return { status: 'offline', detail: 'modelo não instalado' }
    case 'timeout':
      return { status: 'degraded', detail: 'modelo excedeu o tempo' }
    case 'error':
      return { status: 'degraded', detail: 'erro no modelo' }
    default:
      return prev // not_used: the question did not need the model, so nothing was learned
  }
}

function ollamaFromErrorCode(prev: OllamaLink, code: string): OllamaLink {
  if (code === 'model_unavailable') return { status: 'offline', detail: 'modelo indisponível' }
  if (code === 'model_not_found') return { status: 'offline', detail: 'modelo não instalado' }
  if (code === 'model_timeout' || code === 'request_timeout') return { status: 'degraded', detail: 'modelo excedeu o tempo' }
  return prev
}

function octaveFromStatus(s: StatusResponse): OctaveLink {
  const status: OctaveStatus = !s.available ? 'unreachable' : s.state === 'connected' ? 'connected' : 'degraded'
  return {
    status,
    state: s.state,
    simulated: s.simulated,
    source: s.source,
    octaveVersion: s.octave_version,
    protocolVersion: s.protocol_version,
    detail: s.detail,
  }
}

function describeReading(r: TelemetryResponse): string {
  return `RPM ${fmtNumber(r.rpm)} · ${fmtNumber(r.speed_kmh, 0)} km/h · ${fmtNumber(r.coolant_temp_c, 0)} °C`
}

// ───────────────────────── reducer ─────────────────────────
export function reducer(s: AppState, a: Action): AppState {
  switch (a.type) {
    case 'core/online': {
      const wasOnline = s.core.status === 'online'
      const next: AppState = { ...s, core: { status: 'online', version: a.version, latencyMs: a.latencyMs } }
      return wasOnline ? next : log(next, a.at, 'CORE', `Fit AI Core v${a.version} online · ${fmtLatency(a.latencyMs)}`, 'ok')
    }
    case 'core/offline': {
      const wasOffline = s.core.status === 'offline'
      // Without the Core nothing about the car, OCTAVE or the model can be known: forget it all instead of showing it stale.
      const next: AppState = {
        ...s,
        core: { status: 'offline', version: s.core.version, latencyMs: null },
        octave: { ...s.octave, status: 'unknown' },
        ollama: s.ollama.status === 'unknown' ? s.ollama : { status: 'unknown', detail: 'Core offline' },
        chat: { ...s.chat, busy: false },
        telemetry: { phase: 'idle' },
        glance: false,
        live: false,
        responding: false,
      }
      return wasOffline ? next : log(next, a.at, 'CORE', `Core inacessível (${a.reason})`, 'error')
    }
    case 'octave/status': {
      const octave = octaveFromStatus(a.status)
      const changed = octave.status !== s.octave.status || octave.simulated !== s.octave.simulated
      const next = { ...s, octave }
      if (!changed) return next
      const sim = octave.simulated === true ? ' · simulado' : octave.simulated === false ? ' · real' : ''
      if (octave.status === 'connected') return log(next, a.at, 'OCTAVE', `Conectado${sim}`, 'ok')
      if (octave.status === 'degraded') return log(next, a.at, 'OCTAVE', `Ligação com o veículo interrompida${sim}`, 'warn')
      return log(next, a.at, 'OCTAVE', `Indisponível (${a.status.state})`, 'error')
    }
    case 'octave/unknown':
      return s.octave.status === 'unknown' ? s : log({ ...s, octave: { ...s.octave, status: 'unknown' } }, a.at, 'OCTAVE', a.reason, 'warn')
    case 'chat/send': {
      const entries: ChatEntry[] = [...s.chat.entries, { id: a.id, role: 'user', text: a.text, at: a.at }]
      return log({ ...s, chat: { ...s.chat, entries, busy: true }, responding: false }, a.at, 'IA', 'Pensando…')
    }
    case 'chat/done': {
      const r = a.response
      const entries: ChatEntry[] = [...s.chat.entries, { id: a.id, role: 'assistant', text: r.answer, at: a.at, meta: r }]
      const tools = r.used_tools.length
      const level: FeedEvent['level'] = r.fallback_used ? 'warn' : 'ok'
      const next: AppState = {
        ...s,
        chat: { entries, conversationId: r.conversation_id, busy: false },
        ollama: ollamaFromModelStatus(s.ollama, r.model_status),
        responding: true,
        glance: !r.used_tools.includes(TOOL_TELEMETRY) && r.used_tools.includes(TOOL_STATUS) ? true : s.glance,
      }
      return log(next, a.at, 'IA', `${ORIGIN_META[r.answer_origin].label} · ${tools} ferramenta${tools === 1 ? '' : 's'} · ${fmtLatency(r.latency_ms)}`, level)
    }
    case 'chat/failed': {
      const entries: ChatEntry[] = [...s.chat.entries, { id: a.id, role: 'error', text: a.message, at: a.at, code: a.code, requestId: a.requestId }]
      const next: AppState = { ...s, chat: { ...s.chat, entries, busy: false }, ollama: ollamaFromErrorCode(s.ollama, a.code) }
      return log(next, a.at, 'IA', `Falha: ${a.code}`, 'error')
    }
    case 'chat/responding-end':
      return s.responding ? { ...s, responding: false } : s
    case 'telemetry/loading':
      return log({ ...s, telemetry: { phase: 'loading', reason: a.reason } }, a.at, 'TELEMETRIA', 'Consultando o veículo…')
    case 'telemetry/ok': {
      const next: AppState = { ...s, telemetry: { phase: 'ready', reading: a.reading, at: a.at, reason: a.reason }, glance: false }
      if (a.reason === 'live') return next // the live refresh is silent: no feed spam
      const missing = a.reading.missing.length ? ` · sem ${a.reading.missing.join(', ')}` : ''
      return log(next, a.at, 'TELEMETRIA', `${describeReading(a.reading)}${missing}`, a.reading.missing.length ? 'warn' : 'ok')
    }
    case 'telemetry/fail': {
      const next: AppState = { ...s, telemetry: { phase: 'unavailable', code: a.code, message: a.message, at: a.at, reason: a.reason }, glance: false }
      return log(next, a.at, 'TELEMETRIA', a.message, 'error')
    }
    case 'glance/show':
      return { ...s, glance: true }
    case 'glance/hide':
      return s.glance ? { ...s, glance: false } : s
    case 'presentation/clear':
      return { ...s, telemetry: { phase: 'idle' }, glance: false, live: false }
    case 'chat/reset':
      // a new conversation: the Core keeps the old one in its own history, the UI just stops continuing it
      return s.chat.busy ? s : log({ ...s, chat: { entries: [], conversationId: null, busy: false }, responding: false }, a.at, 'IA', 'Nova conversa')
    case 'live/set':
      return { ...s, live: a.value }
  }
}

// ───────────────────────── derived visual mode ─────────────────────────
export type HudMode = 'idle' | 'scanning' | 'thinking' | 'presenting' | 'unavailable' | 'offline'
export type CoreState = 'idle' | 'scanning' | 'thinking' | 'responding' | 'offline'

export interface Derived {
  mode: HudMode
  core: CoreState
  /** HTML callouts shown on the stage. */
  panels: PanelId[]
  /** Car zones that are highlighted. */
  zones: ZoneId[]
  /** Dashed, error-toned zones (no data). */
  faulty: ZoneId[]
}

const ALL_ZONES: ZoneId[] = ['powertrain', 'cooling', 'motion', 'cabin']
/** The regions that carry a reading: the dashboard (ECU) is lit only when there is something to say about the link. */
const READING_ZONES: ZoneId[] = ['powertrain', 'cooling', 'motion']

export function derive(s: AppState): Derived {
  if (s.core.status === 'offline') return { mode: 'offline', core: 'offline', panels: [], zones: [], faulty: [] }
  if (s.chat.busy) return { mode: 'thinking', core: 'thinking', panels: [], zones: [], faulty: [] }
  if (s.telemetry.phase === 'loading') return { mode: 'scanning', core: 'scanning', panels: [], zones: ALL_ZONES, faulty: [] }

  const core: CoreState = s.responding ? 'responding' : 'idle'
  if (s.telemetry.phase === 'ready') {
    return { mode: 'presenting', core, panels: ['rpm', 'speed', 'temp'], zones: READING_ZONES, faulty: [] }
  }
  if (s.telemetry.phase === 'unavailable') {
    return { mode: 'unavailable', core, panels: ['system'], zones: [], faulty: ['cabin'] }
  }
  if (s.glance) return { mode: 'presenting', core, panels: ['system'], zones: ['cabin'], faulty: [] }
  return { mode: 'idle', core, panels: [], zones: [], faulty: [] }
}
