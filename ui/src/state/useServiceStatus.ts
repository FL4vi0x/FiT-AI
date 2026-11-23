import { useEffect, useState } from 'react'
import { createApi, type FitAiApi } from '../api/client'

export type CoreLink = 'checking' | 'online' | 'offline'
export type OctaveLink = 'checking' | 'connected' | 'vehicle_link_down' | 'unavailable' | 'no_core'

export interface ServiceStatus {
  core: CoreLink
  octave: OctaveLink
  /** true when the Core reports that the vehicle data is simulated */
  simulated: boolean | null
  /**
   * The Core exposes no endpoint for Ollama's state (only /health for itself and /vehicle/status for OCTAVE), so the UI
   * cannot know it. It is reported as "not verified" and never as online.
   */
  ollama: 'unverified'
}

export const INITIAL_STATUS: ServiceStatus = { core: 'checking', octave: 'checking', simulated: null, ollama: 'unverified' }

export const POLL_MS = 10_000

/**
 * Real link checks, read-only: GET /health and GET /api/v1/vehicle/status, every 10 s while the tab is visible. It never calls
 * /chat and never reads telemetry. `enabled` false (Standby) means no request at all.
 */
export function useServiceStatus(enabled: boolean, api: FitAiApi = createApi()): ServiceStatus {
  const [status, setStatus] = useState<ServiceStatus>(INITIAL_STATUS)

  useEffect(() => {
    if (!enabled) return
    let stopped = false
    const run = async () => {
      if (document.hidden) return
      try {
        await api.health()
      } catch {
        if (!stopped) setStatus({ ...INITIAL_STATUS, core: 'offline', octave: 'no_core' })
        return
      }
      try {
        const s = await api.status()
        const octave: OctaveLink = s.state === 'connected' ? 'connected' : s.state === 'vehicle_link_down' ? 'vehicle_link_down' : 'unavailable'
        if (!stopped) setStatus({ core: 'online', octave, simulated: s.simulated, ollama: 'unverified' })
      } catch {
        if (!stopped) setStatus({ core: 'online', octave: 'unavailable', simulated: null, ollama: 'unverified' })
      }
    }
    void run()
    const id = setInterval(run, POLL_MS)
    return () => {
      stopped = true
      clearInterval(id)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled])

  return status
}
