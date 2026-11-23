import { useCallback, useEffect, useRef, useState } from 'react'
import { ACTIVATION_END } from '../motion/activeTimeline'

/**
 * The visual states of the Fit AI experience. `listening`, `processing` and `responding` have prepared visuals but NOTHING in
 * the product enters them yet (there is no speech recognition, synthesis or chat call behind this screen): only the development
 * demo can. `unavailable` is shown when the Core link is really down.
 */
export type FitAIVisualState = 'standby' | 'activating' | 'active' | 'listening' | 'processing' | 'responding' | 'unavailable'

export const VISUAL_STATES: readonly FitAIVisualState[] = ['standby', 'activating', 'active', 'listening', 'processing', 'responding', 'unavailable']

/** states in which the active screen is on stage */
export const isOnStage = (s: FitAIVisualState) => s !== 'standby'

export interface VisualStateApi {
  state: FitAIVisualState
  /** standby -> activating -> active. Ignored while already activating or active (an interruption never restarts the sequence). */
  activate: () => void
  /** development demo only: jump to any state */
  demoSet: (s: FitAIVisualState) => void
}

export function useVisualState(opts: { initial?: FitAIVisualState; reduced: boolean }): VisualStateApi {
  const [state, setStateRaw] = useState<FitAIVisualState>(opts.initial ?? 'standby')
  const current = useRef(state)
  const setState = useCallback((s: FitAIVisualState | ((p: FitAIVisualState) => FitAIVisualState)) => {
    current.current = typeof s === 'function' ? s(current.current) : s
    setStateRaw(current.current)
  }, [])
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const clear = () => {
    if (timer.current) clearTimeout(timer.current)
    timer.current = null
  }

  const begin = useCallback(
    (reduced: boolean) => {
      clear()
      if (reduced) {
        setState('active')
        return
      }
      setState('activating')
      timer.current = setTimeout(() => setState((s) => (s === 'activating' ? 'active' : s)), ACTIVATION_END)
    },
    [setState],
  )

  const activate = useCallback(() => {
    if (current.current === 'standby') begin(opts.reduced)
  }, [begin, opts.reduced])

  // opening straight on the active screen (#/active) plays the activation from the start
  useEffect(() => {
    if (opts.initial && opts.initial !== 'standby') begin(opts.reduced)
    return clear
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const demoSet = useCallback((s: FitAIVisualState) => {
    clear()
    setState(s)
  }, [setState])

  return { state, activate, demoSet }
}
