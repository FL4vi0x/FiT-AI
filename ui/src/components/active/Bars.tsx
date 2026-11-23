import type { CSSProperties } from 'react'
import styles from '../../screens/ActiveScreen/ActiveScreen.module.css'

const noise = (i: number) => {
  const s = Math.sin(i * 12.9898) * 43758.5453
  return s - Math.floor(s)
}

/** Waveform as bars (divs animated with transform only, so the loop stays on the compositor). The envelope is fixed. */
export function Bars({ count, sigma = 0.3, className = '' }: { count: number; sigma?: number; className?: string }) {
  return (
    <div className={`${styles.bars} ${className}`} aria-hidden="true">
      {Array.from({ length: count }, (_, i) => {
        const d = (i - (count - 1) / 2) / ((count - 1) / 2)
        const h = Math.max(0.05, Math.exp(-(d * d) / (2 * sigma * sigma)) * (0.5 + 0.5 * noise(i + 1)))
        return <span key={i} className={styles.bar} style={{ '--i': i, '--h': h.toFixed(3) } as CSSProperties} />
      })}
    </div>
  )
}
