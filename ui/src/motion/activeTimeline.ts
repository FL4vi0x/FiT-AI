import type { Span } from './timings'

/**
 * Standby -> Active, in ms from the moment of activation. Same rules as the Standby timeline: only opacity / transform,
 * a single easing family, no flash. The Three.js reveal is started from here too (VEHICLE_REVEAL_AT).
 *
 *   activating  0 .. ACTIVATION_END   light rises, the identity contracts, the car is scanned in, the header and waveform arrive
 *   active      ACTIVATION_END ..     everything settled; only the ambient motion remains
 */
export const ACTIVE_TIMELINE = {
  /** 1. amber light rises, the AI core starts to form */
  light: { delay: 0, duration: 500 },
  core: { delay: 100, duration: 900 },
  /** 2. the Standby identity contracts and leaves; the arcs become the HUD rings */
  identityExit: { delay: 500, duration: 700 },
  rings: { delay: 500, duration: 900 },
  /** 3. the car appears (Three.js reveal) over a lit platform */
  platform: { delay: 900, duration: 1000 },
  vehicle: { delay: 1000, duration: 1400 },
  /** 4. header */
  header: { delay: 1800, duration: 900 },
  /** 5. waveform and settled system */
  waveform: { delay: 2500, duration: 700 },
} as const satisfies Record<string, Span>

export const VEHICLE_REVEAL_AT = ACTIVE_TIMELINE.vehicle.delay
export const ACTIVATION_END = 3200
