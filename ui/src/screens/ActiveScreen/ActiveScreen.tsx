import { motion } from 'motion/react'
import { ActiveHeader } from '../../components/active/ActiveHeader'
import { AICore } from '../../components/active/AICore'
import { AmbientRings } from '../../components/active/AmbientRings'
import { VehiclePlatform } from '../../components/active/VehiclePlatform'
import { VehicleStage } from '../../components/active/VehicleStage'
import { TelemetryReadout } from '../../components/active/TelemetryReadout'
import { VoiceControl } from '../../components/active/VoiceControl'
import { VoiceWaveform } from '../../components/active/VoiceWaveform'
import { lightVariants } from '../../motion/activeVariants'
import { usePrefersReducedMotion } from '../../motion/useReducedMotion'
import type { FitAIVisualState } from '../../state/visualState'
import type { ServiceStatus } from '../../state/useServiceStatus'
import type { TelemetryView } from '../../state/useTelemetry'
import { useNow } from '../../state/useNow'
import type { VoiceInput } from '../../voice/useVoiceInput'
import styles from './ActiveScreen.module.css'

/**
 * Screen 02: the active holographic vehicle interface. Voice-first: no text field, no chat, no bubbles. The visual state comes
 * from outside (see state/visualState.ts); the service chips come from real checks. The AI core doubles as the push-to-talk control
 * (P9.1): speech recognition only, nothing is sent to the chat.
 */
export default function ActiveScreen({ state, services, telemetry = { kind: 'idle' }, voice }: { state: FitAIVisualState; services: ServiceStatus; telemetry?: TelemetryView; voice?: VoiceInput }) {
  const reduced = usePrefersReducedMotion()
  const now = useNow(1000)
  const live = voice?.phase === 'listening' // the microphone is really open: the only time the bars follow it
  return (
    <main className={styles.screen} aria-label="Fit AI" data-testid="active-screen" data-state={state} data-motion={reduced ? 'reduced' : 'full'}>
      <motion.div className={styles.stage} initial={reduced ? false : 'hidden'} animate="visible">
        <motion.div className={styles.light} variants={lightVariants} aria-hidden="true" />
        <AmbientRings />
        <AICore meter={voice?.meter} live={live} />
        <VehiclePlatform />
        <VehicleStage reduced={reduced} />
        <TelemetryReadout view={telemetry} services={services} now={now} />
        <VoiceWaveform meter={voice?.meter} live={live} />
        {voice && state !== 'unavailable' && <VoiceControl voice={voice} />}
        <ActiveHeader services={services} now={now} />
      </motion.div>
    </main>
  )
}
