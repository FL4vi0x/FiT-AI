import type { Transition, Variants } from 'motion/react'
import { EASE_IN_OUT, EASE_OUT, TIMELINE, sec, type Span } from './timings'

/**
 * Typed, reusable variants for the Standby entrance. Only opacity and transforms (and SVG stroke length, which is one
 * attribute per path, run once) are animated: nothing here touches layout, and nothing blurs a large surface.
 * Every delay and duration is read from the shared TIMELINE.
 */
const at = (span: Span, ease: Transition['ease'] = EASE_OUT): Transition => ({ delay: sec(span.delay), duration: sec(span.duration), ease })

export const backgroundVariants: Variants = {
  hidden: { opacity: 0 },
  visible: { opacity: 1, transition: at(TIMELINE.background, EASE_IN_OUT) },
}

/** B. the emblem rises 8 px and grows from 0.96 to 1 */
export const emblemVariants: Variants = {
  hidden: { opacity: 0, y: 8, scale: 0.96 },
  visible: { opacity: 1, y: 0, scale: 1, transition: at(TIMELINE.emblem) },
}

/** the amber rim comes up a little after the emblem itself, so the light seems to grow out of the metal */
export const rimGlowVariants: Variants = {
  hidden: { opacity: 0 },
  visible: { opacity: 1, transition: { delay: sec(TIMELINE.emblem.delay + 250), duration: sec(TIMELINE.emblem.duration), ease: EASE_IN_OUT } },
}

/** C. the wordmark: one soft fade with a small rise, never a typewriter */
export const wordmarkVariants: Variants = {
  hidden: { opacity: 0, y: 6 },
  visible: { opacity: 1, y: 0, transition: at(TIMELINE.wordmark) },
}

/** C'. the single glint across the lettering: a slanted light band travels once from left to right */
export const sweepVariants: Variants = {
  hidden: { x: -140, opacity: 0 },
  visible: { x: 460, opacity: [0, 0.9, 0.9, 0], transition: { delay: sec(TIMELINE.wordmarkSweep.delay), duration: sec(TIMELINE.wordmarkSweep.duration), ease: EASE_IN_OUT, times: [0, 0.15, 0.8, 1] } },
}

/** D. an arc draws itself upwards from the floor; `order` staggers the four ridges */
export const arcVariants: Variants = {
  hidden: { pathLength: 0, opacity: 0 },
  visible: (order: number = 0) => ({
    pathLength: 1,
    opacity: 1,
    transition: { delay: sec(TIMELINE.arcs.delay + order * 160), duration: sec(TIMELINE.arcs.duration), ease: EASE_OUT },
  }),
}

/** E. the light under the identity opens horizontally from a point */
export const horizonVariants: Variants = {
  hidden: { opacity: 0, scaleX: 0.04 },
  visible: { opacity: 1, scaleX: 1, transition: at(TIMELINE.horizon) },
}

/** the pool of light and the faint lines on the floor arrive after the light itself */
export const poolVariants: Variants = {
  hidden: { opacity: 0 },
  visible: { opacity: 1, transition: { delay: sec(TIMELINE.horizon.delay + 350), duration: sec(TIMELINE.horizon.duration), ease: EASE_IN_OUT } },
}

export const sideLineVariants: Variants = {
  hidden: { opacity: 0, scaleX: 0.2 },
  visible: { opacity: 1, scaleX: 1, transition: at(TIMELINE.sideLines) },
}

export const reflectionVariants: Variants = {
  hidden: { opacity: 0 },
  visible: { opacity: 1, transition: at(TIMELINE.reflection, EASE_IN_OUT) },
}
