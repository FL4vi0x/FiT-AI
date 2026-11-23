import { useEffect, useState } from 'react'
import { ApiError, createApi, NetworkError, type FitAiApi } from '../api/client'
import type { TelemetryResponse } from '../api/types'

/** What the screen knows about the vehicle readings. Nothing here is invented: a value is either what the Core returned or absent. */
export type TelemetryView =
  | { kind: 'idle' } // not asked yet (the screen is not on stage)
  | { kind: 'loading' }
  | { kind: 'ok'; reading: TelemetryResponse; receivedAt: number }
  | { kind: 'error'; code: string; message: string }

export const TELEMETRY_POLL_MS = 2_000

/**
 * Reads GET /api/v1/vehicle/telemetry every 2 s while `enabled` and the tab is visible. Read-only: it never calls /chat. A new request
 * starts only after the previous one finished (a slow OCTAVE never piles requests up), and nothing runs once unmounted.
 * A failed read replaces the readings with the error: the last good values are NOT kept on screen as if they were current.
 */
export function useTelemetry(enabled: boolean, api: FitAiApi = createApi(), intervalMs: number = TELEMETRY_POLL_MS): TelemetryView {
  const [view, setView] = useState<TelemetryView>({ kind: 'idle' })

  useEffect(() => {
    if (!enabled) return
    let stopped = false
    let timer: ReturnType<typeof setTimeout> | null = null
    setView((v) => (v.kind === 'idle' ? { kind: 'loading' } : v))

    const schedule = () => {
      if (!stopped) timer = setTimeout(run, intervalMs)
    }
    const run = async () => {
      timer = null
      if (document.hidden) return // resumed by the visibilitychange listener
      try {
        const reading = await api.telemetry()
        if (!stopped) setView({ kind: 'ok', reading, receivedAt: Date.now() })
      } catch (e) {
        if (stopped) return
        if (e instanceof ApiError) setView({ kind: 'error', code: e.code, message: e.message })
        else if (e instanceof NetworkError) setView({ kind: 'error', code: e.kind === 'timeout' ? 'octave_timeout' : 'core_offline', message: e.message })
        else setView({ kind: 'error', code: 'invalid_response', message: 'Resposta do Core fora do formato esperado' })
      }
      schedule()
    }
    const onVisibility = () => {
      if (!document.hidden && !stopped && timer === null) void run()
    }
    document.addEventListener('visibilitychange', onVisibility)
    void run()
    return () => {
      stopped = true
      if (timer) clearTimeout(timer)
      document.removeEventListener('visibilitychange', onVisibility)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, intervalMs])

  return view
}
