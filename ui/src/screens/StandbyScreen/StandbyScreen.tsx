import { motion } from 'motion/react'
import { AmbientArcs } from '../../components/standby/AmbientArcs'
import { AmbientReflection } from '../../components/standby/AmbientReflection'
import { FitAiWordmark } from '../../components/standby/FitAiWordmark'
import { HondaEmblem } from '../../components/standby/HondaEmblem'
import { Layer } from '../../components/standby/Layer'
import { LightHorizon } from '../../components/standby/LightHorizon'
import { backgroundVariants } from '../../motion/variants'
import { usePrefersReducedMotion } from '../../motion/useReducedMotion'
import { useStandbyPhase } from '../../motion/useStandbyPhase'
import styles from './StandbyScreen.module.css'

/**
 * Screen 01: Standby. Pure presentation: no backend, no requests, no controls. A black room, the emblem and the FIT AI
 * wordmark centred, two thin arcs on each side and a line of amber light under the identity.
 */
export default function StandbyScreen() {
  const reduced = usePrefersReducedMotion()
  const phase = useStandbyPhase(reduced)
  const loops = phase === 'idle' && !reduced
  const initial = reduced ? false : 'hidden'

  return (
    <main className={styles.screen} aria-label="Fit AI, em espera" data-testid="standby-screen" data-phase={phase} data-motion={reduced ? 'reduced' : 'full'}>
      <motion.div className={styles.stage} initial={initial} animate="visible">
        <motion.div variants={backgroundVariants} className={styles.layer} aria-hidden="true">
          <div className={`${styles.halo} ${loops ? styles.loopHalo : ''}`} />
        </motion.div>
        <Layer testId="standby-arcs">
          <AmbientArcs innerClass={loops ? styles.loopInner : undefined} outerClass={loops ? styles.loopOuter : undefined} />
        </Layer>
        <Layer testId="standby-light">
          <LightHorizon className={loops ? styles.loopHorizon : undefined} />
        </Layer>
        <Layer testId="standby-reflection">
          <AmbientReflection />
        </Layer>
        <svg className={styles.layer} viewBox="0 0 1672 941" role="img" aria-label="Fit AI" data-testid="standby-logo">
          <HondaEmblem />
          <FitAiWordmark />
        </svg>
      </motion.div>
    </main>
  )
}
