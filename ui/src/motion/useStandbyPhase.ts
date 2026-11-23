import { useEffect, useState } from 'react'
import { ENTERING_END, SETTLING_END, type StandbyPhase } from './timings'

/**
 * The visual phase of the Standby screen: entering, then settling, then idle, driven by two timers that are always cleaned
 * up. With reduced motion there is no sequence at all: the screen is idle (its final state) from the first render.
 */
export function useStandbyPhase(reduced: boolean): StandbyPhase {
  const [phase, setPhase] = useState<StandbyPhase>(reduced ? 'idle' : 'entering')

  useEffect(() => {
    if (reduced) {
      setPhase('idle')
      return
    }
    setPhase('entering')
    const toSettling = setTimeout(() => setPhase('settling'), ENTERING_END)
    const toIdle = setTimeout(() => setPhase('idle'), SETTLING_END)
    return () => {
      clearTimeout(toSettling)
      clearTimeout(toIdle)
    }
  }, [reduced])

  return phase
}
