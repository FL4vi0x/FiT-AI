/**
 * The live loudness of the microphone, shared between the voice input (which feeds it) and the HUD (which reads it every frame).
 * It lives outside React state on purpose: a value that changes ~25 times per second must not re-render the screen. Only real
 * captured audio ever goes in: `reset()` flattens it as soon as the microphone is off, so nothing can look like "listening" by itself.
 */
export interface LevelMeter {
  /** `history[0]` is the newest smoothed level (0..1), older ones follow. Never reallocated. */
  readonly history: Float32Array
  push(level: number): void
  reset(): void
  /** the newest smoothed level */
  current(): number
}

export function createLevelMeter(size = 64): LevelMeter {
  const history = new Float32Array(size)
  return {
    history,
    push(level) {
      const clean = Number.isFinite(level) ? Math.max(0, Math.min(1, level)) : 0
      const previous = history[0] as number
      history.copyWithin(1, 0, size - 1)
      // fast attack, slower release: a syllable is visible and the bars do not flicker between blocks
      history[0] = Math.max(clean, previous * 0.8)
    },
    reset() {
      history.fill(0)
    },
    current: () => history[0] as number,
  }
}
