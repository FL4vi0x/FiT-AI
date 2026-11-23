import { useEffect, useState } from 'react'
import { createApi, type FitAiApi } from '../api/client'
import type { LlmState } from '../api/types'

export type CoreLink = 'checking' | 'online' | 'offline'
export type OctaveLink = 'checking' | 'connected' | 'vehicle_link_down' | 'unavailable' | 'no_core'

export interface ServiceStatus {
  core: CoreLink
  octave: OctaveLink
  /** true when the Core reports that the vehicle data is simulated */
  simulated: boolean | null
  /**
   * The language-model server, from the Core's read-only GET /api/v1/llm/status. `unverified` when the check could not be
   * completed, when the Core is unreachable or when it predates the endpoint: never reported as available without proof.
   */
  ollama: 'checking' | LlmState
}

const LLM_STATES: readonly LlmState[] = ['available', 'model_not_installed', 'unavailable', 'unverified', 'not_configured']

/** The Core's answer is data, not code: an unknown or malformed state (a newer Core, a proxy page) is "not verified", never a crash. */
export function toLlmState(value: unknown): LlmState {
  return typeof value === 'string' && (LLM_STATES as readonly string[]).includes(value) ? (value as LlmState) : 'unverified'
}

export const INITIAL_STATUS: ServiceStatus = { core: 'checking', octave: 'checking', simulated: null, ollama: 'checking' }

export const POLL_MS = 10_000

/**
 * Real link checks, read-only: GET /health, GET /api/v1/vehicle/status and GET /api/v1/llm/status, every 10 s while the tab is
 * visible. It never calls /chat and never reads telemetry. `enabled` false (Standby) means no request at all.
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
        if (!stopped) setStatus({ core: 'offline', octave: 'no_core', simulated: null, ollama: 'unverified' })
        return
      }
      // the two checks are independent: a failure of one must not hide the other
      const [vehicle, llm] = await Promise.allSettled([api.status(), api.llmStatus()])
      const ollama: ServiceStatus['ollama'] = llm.status === 'fulfilled' ? toLlmState(llm.value?.state) : 'unverified'
      if (stopped) return
      if (vehicle.status === 'fulfilled') {
        const s = vehicle.value
        const octave: OctaveLink = s.state === 'connected' ? 'connected' : s.state === 'vehicle_link_down' ? 'vehicle_link_down' : 'unavailable'
        setStatus({ core: 'online', octave, simulated: s.simulated, ollama })
      } else {
        setStatus({ core: 'online', octave: 'unavailable', simulated: null, ollama })
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
