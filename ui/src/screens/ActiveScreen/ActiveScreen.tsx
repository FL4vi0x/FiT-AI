import { motion } from 'motion/react'
import { ActiveHeader } from '../../components/active/ActiveHeader'
import { AICore } from '../../components/active/AICore'
import { AmbientRings } from '../../components/active/AmbientRings'
import { VehiclePlatform } from '../../components/active/VehiclePlatform'
import { VehicleStage } from '../../components/active/VehicleStage'
import { VoiceWaveform } from '../../components/active/VoiceWaveform'
import { lightVariants } from '../../motion/activeVariants'
import { usePrefersReducedMotion } from '../../motion/useReducedMotion'
import type { FitAIVisualState } from '../../state/visualState'
import type { ServiceStatus } from '../../state/useServiceStatus'
import { useNow } from '../../state/useNow'
import styles from './ActiveScreen.module.css'

/**
 * Screen 02: the active holographic vehicle interface. Voice-first: no text field, no chat, no bubbles. The visual state comes
 * from outside (see state/visualState.ts); the service chips come from real checks.
 */
export default function ActiveScreen({ state, services }: { state: FitAIVisualState; services: ServiceStatus }) {
  const reduced = usePrefersReducedMotion()
  const now = useNow(1000)
  return (
    <main className={styles.screen} aria-label="Fit AI" data-testid="active-screen" data-state={state} data-motion={reduced ? 'reduced' : 'full'}>
      <motion.div className={styles.stage} initial={reduced ? false : 'hidden'} animate="visible">
        <motion.div className={styles.light} variants={lightVariants} aria-hidden="true" />
        <AmbientRings />
        <AICore />
        <VehiclePlatform />
        <VehicleStage reduced={reduced} />
        <VoiceWaveform />
        <ActiveHeader services={services} now={now} />
      </motion.div>
    </main>
  )
}
