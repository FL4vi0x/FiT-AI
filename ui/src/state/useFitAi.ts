import { useCallback, useEffect, useMemo, useReducer, useRef } from 'react'
import { ApiError, NetworkError, type FitAiApi } from '../api/client'
import { MAX_MESSAGE_CHARS, TOOL_TELEMETRY } from '../api/types'
import { errorText } from '../lib/labels'
import { derive, initialState, reducer, type ScanReason } from './store'

export interface UseFitAiOptions {
  /** Link polling (GET /health + /vehicle/status): cheap and read-only. Telemetry is NEVER polled while idle. */
  pollMs?: number
  /** Refresh period of the optional "live" mode. */
  liveMs?: number
  /** How long the core shows "responding" after an answer. */
  respondingMs?: number
  now?: () => number
}

let counter = 0
const uid = (p: string) => `${p}-${Date.now().toString(36)}-${(counter++).toString(36)}`

/** Orchestrates the real API calls and exposes the state the HUD renders. No data is ever fabricated here. */
export function useFitAi(api: FitAiApi, opts: UseFitAiOptions = {}) {
  const { pollMs = 5_000, liveMs = 2_000, respondingMs = 2_400, now = Date.now } = opts
  const [state, dispatch] = useReducer(reducer, undefined, initialState)
  const stateRef = useRef(state)
  stateRef.current = state
  const mounted = useRef(true)

  const guarded = useCallback(
    <A,>(fn: (a: A) => void) =>
      (a: A) => {
        if (mounted.current) fn(a)
      },
    [],
  )
  const safeDispatch = useMemo(() => guarded(dispatch), [guarded])

  /** Core liveness + OCTAVE link. Returns whether the Core answered. */
  const refreshLinks = useCallback(async (): Promise<boolean> => {
    const t0 = performance.now()
    try {
      const h = await api.health()
      safeDispatch({ type: 'core/online', at: now(), version: h.version, latencyMs: performance.now() - t0 })
    } catch (e) {
      // the dev/preview proxy answers 5xx when the Core is down: from the UI's side that is "no answer" as well
      safeDispatch({ type: 'core/offline', at: now(), reason: e instanceof NetworkError ? e.message : 'sem resposta do Core' })
      return false
    }
    try {
      safeDispatch({ type: 'octave/status', at: now(), status: await api.status() })
    } catch (e) {
      safeDispatch({ type: 'octave/unknown', at: now(), reason: e instanceof ApiError ? errorText(e.code, e.message) : 'Status do OCTAVE indisponível' })
    }
    return true
  }, [api, now, safeDispatch])

  const scanTelemetry = useCallback(
    async (reason: ScanReason = 'manual') => {
      if (reason !== 'live') safeDispatch({ type: 'telemetry/loading', at: now(), reason })
      try {
        const reading = await api.telemetry()
        safeDispatch({ type: 'telemetry/ok', at: now(), reading, reason })
      } catch (e) {
        if (e instanceof ApiError) {
          safeDispatch({ type: 'telemetry/fail', at: now(), code: e.code, message: errorText(e.code, e.message), reason })
        } else if (e instanceof NetworkError && e.kind === 'timeout') {
          // a slow answer is "no reading", not "no Core": the link poll (GET /health) decides whether the Core is gone
          safeDispatch({ type: 'telemetry/fail', at: now(), code: 'timeout', message: 'O Core não respondeu a tempo à leitura.', reason })
        } else {
          safeDispatch({ type: 'core/offline', at: now(), reason: 'sem resposta' })
        }
      }
    },
    [api, now, safeDispatch],
  )

  const sendMessage = useCallback(
    async (raw: string): Promise<boolean> => {
      const text = raw.trim()
      const s = stateRef.current
      if (!text || text.length > MAX_MESSAGE_CHARS || s.chat.busy || s.core.status === 'offline') return false
      const userId = uid('u')
      safeDispatch({ type: 'chat/send', at: now(), id: userId, text })
      try {
        const response = await api.chat({ message: text, conversation_id: s.chat.conversationId })
        safeDispatch({ type: 'chat/done', at: now(), id: uid('a'), response })
        // The chat answer does not carry the sensor values, so the callouts come from a direct read of the existing
        // telemetry endpoint, taken right after the answer and labelled as such.
        if (response.used_tools.includes(TOOL_TELEMETRY)) void scanTelemetry('chat')
      } catch (e) {
        if (e instanceof ApiError) {
          let message = errorText(e.code, e.message)
          if (e.code === 'service_busy' && e.retryAfterS) message += ` (tente em ${e.retryAfterS} s)`
          safeDispatch({ type: 'chat/failed', at: now(), id: uid('e'), code: e.code, message, requestId: e.requestId })
        } else {
          const offline = e instanceof NetworkError && e.kind === 'offline'
          safeDispatch({ type: 'chat/failed', at: now(), id: uid('e'), code: offline ? 'offline' : 'timeout', message: offline ? 'Fit AI Core inacessível.' : 'O Core não respondeu a tempo.', requestId: null })
          if (offline) safeDispatch({ type: 'core/offline', at: now(), reason: 'sem resposta' })
        }
      }
      return true
    },
    [api, now, safeDispatch, scanTelemetry],
  )

  const clearPresentation = useCallback(() => safeDispatch({ type: 'presentation/clear', at: now() }), [now, safeDispatch])
  const setLive = useCallback((value: boolean) => safeDispatch({ type: 'live/set', value }), [safeDispatch])
  const newConversation = useCallback(() => safeDispatch({ type: 'chat/reset', at: now() }), [now, safeDispatch])

  // boot: the first look at the link is real, and silent: the screen stays clean unless something is wrong
  useEffect(() => {
    mounted.current = true
    void refreshLinks()
    return () => {
      mounted.current = false
    }
  }, [refreshLinks])

  // link polling, only while the page is visible
  useEffect(() => {
    const id = setInterval(() => {
      if (typeof document === 'undefined' || document.visibilityState === 'visible') void refreshLinks()
    }, pollMs)
    return () => clearInterval(id)
  }, [refreshLinks, pollMs])

  // optional live mode: refresh the projected reading while it is on screen
  const showingReading = state.telemetry.phase === 'ready'
  useEffect(() => {
    if (!state.live || !showingReading) return
    const id = setInterval(() => {
      if (typeof document === 'undefined' || document.visibilityState === 'visible') void scanTelemetry('live')
    }, liveMs)
    return () => clearInterval(id)
  }, [state.live, showingReading, liveMs, scanTelemetry])

  // the "responding" core state is brief
  useEffect(() => {
    if (!state.responding) return
    const id = setTimeout(() => safeDispatch({ type: 'chat/responding-end' }), respondingMs)
    return () => clearTimeout(id)
  }, [state.responding, respondingMs, safeDispatch])

  const derived = useMemo(() => derive(state), [state])
  return { state, derived, sendMessage, scanTelemetry, clearPresentation, setLive, newConversation, refreshLinks }
}
