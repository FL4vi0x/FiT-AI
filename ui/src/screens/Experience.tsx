import { motion } from 'motion/react'
import { useState } from 'react'
import { identityExit } from '../motion/activeVariants'
import { usePrefersReducedMotion } from '../motion/useReducedMotion'
import { isOnStage, useVisualState, VISUAL_STATES, type FitAIVisualState } from '../state/visualState'
import { useServiceStatus } from '../state/useServiceStatus'
import ActiveScreen from './ActiveScreen/ActiveScreen'
import StandbyScreen from './StandbyScreen/StandbyScreen'
import activeStyles from './ActiveScreen/ActiveScreen.module.css'
import styles from './Experience.module.css'

/**
 * Orchestrates Standby -> Active. Both screens are mounted during the transition: the active one underneath builds itself on its
 * own timeline while the Standby identity contracts (uniform scale, never deformed) and fades above it. The only trigger is the
 * user (the wake control, keyboard or pointer): there is no voice service, so nothing activates the screen by itself.
 */
export default function Experience({ initial = 'standby', demo = false }: { initial?: FitAIVisualState; demo?: boolean }) {
  const reduced = usePrefersReducedMotion()
  const { state, activate, demoSet } = useVisualState({ initial, reduced })
  const onStage = isOnStage(state)
  const [standbyGone, setStandbyGone] = useState(initial !== 'standby')
  const services = useServiceStatus(onStage)

  // the real link decides `unavailable`; the demo can force any state
  const shown: FitAIVisualState = state === 'active' && services.core === 'offline' ? 'unavailable' : state

  const showStandby = !standbyGone || !onStage
  return (
    <>
      {onStage && <ActiveScreen state={shown} services={services} />}
      {showStandby && (
        <motion.div
          className={styles.standby}
          initial={false}
          animate={onStage ? { opacity: 0, scale: 0.6, y: -40 } : { opacity: 1, scale: 1, y: 0 }}
          transition={reduced ? { duration: 0 } : identityExit}
          onAnimationComplete={() => onStage && setStandbyGone(true)}
          aria-hidden={onStage ? true : undefined}
          data-testid="standby-layer"
        >
          <StandbyScreen />
          {!onStage && <button type="button" className={styles.wake} aria-label="Ativar o Fit AI" onClick={activate} data-testid="wake" />}
        </motion.div>
      )}
      {demo && import.meta.env.DEV && (
        <div className={activeStyles.demo} role="group" aria-label="Demonstração (somente desenvolvimento)" data-testid="demo-panel">
          {VISUAL_STATES.map((s) => (
            <button key={s} type="button" aria-pressed={state === s} onClick={() => (s === 'standby' ? (setStandbyGone(false), demoSet(s)) : demoSet(s))}>
              {s}
            </button>
          ))}
        </div>
      )}
    </>
  )
}
