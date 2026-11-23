/**
 * The one timeline of the Standby screen, in milliseconds from mount. Everything that moves reads its delay and duration
 * from here, so the choreography can be tuned (or reasoned about in a test) in a single place.
 *
 * Phases are internal to this screen. They never touch the chat API and do not pretend to be a connection to anything:
 *
 *   entering  0 .. ENTERING_END   the background wakes, the emblem and the wordmark arrive
 *   settling  .. SETTLING_END     the arcs and the light finish; nothing new appears
 *   idle      SETTLING_END ..     the screen is (almost) still; only the ambient loops remain
 */
export type StandbyPhase = 'entering' | 'settling' | 'idle'

export interface Span {
  /** ms after mount */
  delay: number
  /** ms */
  duration: number
}

export const TIMELINE = {
  /** A. the room: a radial glow fades in from black, no flash */
  background: { delay: 0, duration: 400 },
  /** B. the emblem rises 8 px and grows from 0.96 to 1, its amber rim comes up with it */
  emblem: { delay: 400, duration: 900 },
  /** C. the wordmark arrives under it (one fade, no typewriter) */
  wordmark: { delay: 900, duration: 700 },
  /** C'. a single metallic glint travels across the wordmark, once */
  wordmarkSweep: { delay: 1350, duration: 950 },
  /** D. the two pairs of arcs draw themselves in, very slowly */
  arcs: { delay: 1200, duration: 1200 },
  /** E. a point of amber light under the identity opens into the horizon; the reflection follows */
  horizon: { delay: 1500, duration: 1100 },
  sideLines: { delay: 1600, duration: 800 },
  reflection: { delay: 1900, duration: 800 },
} as const satisfies Record<string, Span>

export const ENTERING_END = 1600
export const SETTLING_END = 2600

/** Ambient loops (CSS, opacity only). Periods are long on purpose: the change should be almost imperceptible. */
export const LOOP = {
  /** the halo behind the emblem breathes */
  halo: { seconds: 9, from: 0.84, to: 1 },
  /** the arcs drift a few percent in brightness, each at its own period so they never beat together */
  arcsInner: { seconds: 11, from: 0.86, to: 1 },
  arcsOuter: { seconds: 14, from: 0.8, to: 1 },
  /** the light under the identity */
  horizon: { seconds: 8, from: 0.86, to: 1 },
} as const

/** The classic "expo-out" feel without overshoot: no bounce anywhere. */
export const EASE_OUT: [number, number, number, number] = [0.22, 1, 0.36, 1]
export const EASE_IN_OUT: [number, number, number, number] = [0.45, 0, 0.55, 1]

export const sec = (ms: number): number => ms / 1000
