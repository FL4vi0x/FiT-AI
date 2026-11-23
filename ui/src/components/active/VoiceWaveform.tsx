import { motion } from 'motion/react'
import { waveformVariants } from '../../motion/activeVariants'
import { Bars } from './Bars'
import styles from '../../screens/ActiveScreen/ActiveScreen.module.css'

/** The bottom waveform with its two side arcs. Purely visual: it does not capture or play any audio. */
export function VoiceWaveform() {
  return (
    <motion.div className={styles.voice} variants={waveformVariants} data-testid="voice-waveform" aria-hidden="true">
      <svg className={styles.voiceArcs} viewBox="0 0 600 120" preserveAspectRatio="none">
        <path d="M 38 8 Q 4 60 38 112" fill="none" stroke="#FF8500" strokeWidth="2.6" opacity="0.9" strokeLinecap="round" />
        <path d="M 38 8 Q 4 60 38 112" fill="none" stroke="#FF8500" strokeWidth="9" opacity="0.15" strokeLinecap="round" />
        <path d="M 562 8 Q 596 60 562 112" fill="none" stroke="#FF8500" strokeWidth="2.6" opacity="0.9" strokeLinecap="round" />
        <path d="M 562 8 Q 596 60 562 112" fill="none" stroke="#FF8500" strokeWidth="9" opacity="0.15" strokeLinecap="round" />
        <line x1="60" y1="60" x2="540" y2="60" stroke="#FF8500" strokeWidth="1" opacity="0.5" />
      </svg>
      <Bars count={61} sigma={0.3} className={styles.voiceBars} />
    </motion.div>
  )
}
