import { useEffect, useRef, type CSSProperties } from 'react'
import { usePrefersReducedMotion } from '../../motion/useReducedMotion'
import type { LevelMeter } from '../../voice/levels'
import styles from '../../screens/ActiveScreen/ActiveScreen.module.css'

const noise = (i: number) => {
  const s = Math.sin(i * 12.9898) * 43758.5453
  return s - Math.floor(s)
}

/** lowest bar scale while driven by the microphone: the same resting height the CSS uses for the listening state */
const REST = 0.15
/** with reduced motion the bars still show the microphone level (it is information, not decoration) but update slowly and never glide */
const REDUCED_FRAME_MS = 125

/**
 * Waveform as bars (divs animated with transform only, so the loop stays on the compositor). The envelope is fixed.
 *
 * By default each bar loops on its own CSS animation (ambient). When `live` is true, and only then, the CSS loop is off (see the
 * `listening` rules in the stylesheet) and the bars follow the REAL microphone level from `meter`: the newest sample at the centre,
 * older ones flowing outwards. When `live` goes false the inline transforms are removed, so a bar never keeps a stale microphone height.
 */
export function Bars({ count, sigma = 0.3, className = '', meter, live = false }: { count: number; sigma?: number; className?: string; meter?: LevelMeter; live?: boolean }) {
  const host = useRef<HTMLDivElement>(null)
  const reduced = usePrefersReducedMotion()

  useEffect(() => {
    const el = host.current
    if (!live || !meter || !el) return
    const bars = Array.from(el.children) as HTMLElement[]
    const mid = (bars.length - 1) / 2
    let frame = 0
    let last = -Infinity
    const paint = (now: number) => {
      frame = requestAnimationFrame(paint)
      if (reduced && now - last < REDUCED_FRAME_MS) return
      last = now
      const h = meter.history
      for (let i = 0; i < bars.length; i++) {
        const level = h[Math.min(h.length - 1, Math.round(Math.abs(i - mid)))] as number
        bars[i]!.style.transform = `scaleY(${(REST + (1 - REST) * level).toFixed(3)})`
      }
    }
    frame = requestAnimationFrame(paint)
    return () => {
      cancelAnimationFrame(frame)
      for (const b of bars) b.style.transform = ''
    }
  }, [live, meter, reduced])

  return (
    <div ref={host} className={`${styles.bars} ${className}`} aria-hidden="true">
      {Array.from({ length: count }, (_, i) => {
        const d = (i - (count - 1) / 2) / ((count - 1) / 2)
        const h = Math.max(0.05, Math.exp(-(d * d) / (2 * sigma * sigma)) * (0.5 + 0.5 * noise(i + 1)))
        return <span key={i} className={styles.bar} style={{ '--i': i, '--h': h.toFixed(3) } as CSSProperties} />
      })}
    </div>
  )
}
