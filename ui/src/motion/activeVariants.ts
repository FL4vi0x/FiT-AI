import type { Transition, Variants } from 'motion/react'
import { EASE_IN_OUT, EASE_OUT, sec, type Span } from './timings'
import { ACTIVE_TIMELINE } from './activeTimeline'

const at = (span: Span, ease: Transition['ease'] = EASE_OUT): Transition => ({ delay: sec(span.delay), duration: sec(span.duration), ease })

/** Container states: the active screen enters when `animate="visible"` is set, and leaves to `hidden` if it ever has to. */
export const lightVariants: Variants = { hidden: { opacity: 0 }, visible: { opacity: 1, transition: at(ACTIVE_TIMELINE.light, EASE_IN_OUT) } }

export const coreVariants: Variants = {
  hidden: { opacity: 0, scale: 0.9 },
  visible: { opacity: 1, scale: 1, transition: at(ACTIVE_TIMELINE.core) },
}

export const ringsVariants: Variants = { hidden: { opacity: 0, scale: 0.97 }, visible: { opacity: 1, scale: 1, transition: at(ACTIVE_TIMELINE.rings) } }

export const platformVariants: Variants = { hidden: { opacity: 0, scale: 0.92 }, visible: { opacity: 1, scale: 1, transition: at(ACTIVE_TIMELINE.platform) } }

export const headerVariants: Variants = { hidden: { opacity: 0, y: -14 }, visible: { opacity: 1, y: 0, transition: at(ACTIVE_TIMELINE.header) } }

export const waveformVariants: Variants = { hidden: { opacity: 0, y: 10 }, visible: { opacity: 1, y: 0, transition: at(ACTIVE_TIMELINE.waveform) } }

/** The Standby identity contracting out of the way: it shrinks (never deformed: uniform scale) and fades. */
export const identityExit: Transition = at(ACTIVE_TIMELINE.identityExit, EASE_IN_OUT)
