import { motion } from 'motion/react'
import { useEffect, useRef } from 'react'
import type { LevelMeter } from '../../voice/levels'
import { coreVariants } from '../../motion/activeVariants'
import { Bars } from './Bars'
import styles from '../../screens/ActiveScreen/ActiveScreen.module.css'

const CX = 836
const CY = 218

const polar = (r: number, deg: number): [number, number] => [CX + r * Math.cos((deg * Math.PI) / 180), CY + r * Math.sin((deg * Math.PI) / 180)]
const arc = (r: number, a0: number, a1: number) => {
  const [x0, y0] = polar(r, a0)
  const [x1, y1] = polar(r, a1)
  return `M ${x0.toFixed(1)} ${y0.toFixed(1)} A ${r} ${r} 0 ${a1 - a0 > 180 ? 1 : 0} 1 ${x1.toFixed(1)} ${y1.toFixed(1)}`
}

const TICKS = Array.from({ length: 60 }, (_, i) => i * 6)

/** The AI core above the car: segmented outer ring, luminous inner ring, radial ticks and a small waveform. It is independent of the 3D scene.
 * While `live` (the microphone is really on) it also glows with the captured level; otherwise the glow is off, never faked. */
export function AICore({ meter, live = false }: { meter?: LevelMeter; live?: boolean }) {
  const glow = useRef<SVGCircleElement>(null)
  useEffect(() => {
    const el = glow.current
    if (!live || !meter || !el) return
    let frame = 0
    const paint = () => {
      frame = requestAnimationFrame(paint)
      el.style.opacity = (0.3 + 0.7 * meter.current()).toFixed(3) // a steady glow while open, brighter with the voice
    }
    frame = requestAnimationFrame(paint)
    return () => {
      cancelAnimationFrame(frame)
      el.style.opacity = ''
    }
  }, [live, meter])
  return (
    <motion.div className={styles.core} variants={coreVariants} data-testid="ai-core" aria-hidden="true">
      <svg className={styles.coreSvg} viewBox="0 0 1672 941">
        <defs>
          <radialGradient id="core-haze" cx="0.5" cy="0.5" r="0.5">
            <stop offset="0" stopColor="#FF8500" stopOpacity="0.16" />
            <stop offset="1" stopColor="#FF8500" stopOpacity="0" />
          </radialGradient>
          <radialGradient id="core-listen" cx="0.5" cy="0.5" r="0.5">
            <stop offset="0.55" stopColor="#FFB04A" stopOpacity="0.55" />
            <stop offset="1" stopColor="#FF8500" stopOpacity="0" />
          </radialGradient>
        </defs>
        <circle cx={CX} cy={CY} r={250} fill="url(#core-haze)" />
        <circle ref={glow} className={styles.coreListenGlow} cx={CX} cy={CY} r={190} fill="url(#core-listen)" />
        {[175, 205, 235].map((r, i) => (
          <circle key={r} cx={CX} cy={CY} r={r} fill="none" stroke="#FF8500" strokeWidth="1" opacity={0.2 - i * 0.05} />
        ))}
        <line x1="520" y1="190" x2="740" y2="205" stroke="#FF8500" strokeWidth="1" opacity="0.25" />
        <line x1="1150" y1="190" x2="932" y2="205" stroke="#FF8500" strokeWidth="1" opacity="0.25" />
        <g className={styles.coreSegments}>
          {[[205, 232], [300, 326], [25, 52], [118, 146]].map(([a, b]) => (
            <g key={a}>
              <path d={arc(150, a!, b!)} fill="none" stroke="#FF8500" strokeWidth="14" opacity="0.14" strokeLinecap="round" />
              <path d={arc(150, a!, b!)} fill="none" stroke="#FF9A1F" strokeWidth="6" opacity="0.85" strokeLinecap="butt" />
            </g>
          ))}
          <circle cx={CX} cy={CY} r={150} fill="none" stroke="#FF8500" strokeWidth="1" strokeDasharray="2 7" opacity="0.5" />
        </g>
        <g className={styles.coreTicks}>
          {TICKS.map((a) => {
            const [x0, y0] = polar(120, a)
            const [x1, y1] = polar(a % 30 === 0 ? 134 : 127, a)
            return <line key={a} x1={x0} y1={y0} x2={x1} y2={y1} stroke="#FFB04A" strokeWidth="1.3" opacity="0.4" />
          })}
        </g>
        <circle cx={CX} cy={CY} r={112} fill="none" stroke="#FF8500" strokeWidth="16" opacity="0.14" />
        <circle cx={CX} cy={CY} r={112} fill="none" stroke="#FF9A1F" strokeWidth="3.4" />
        <circle cx={CX} cy={CY} r={102} fill="none" stroke="#FFB04A" strokeWidth="1.2" opacity="0.7" />
        <line x1={CX - 88} y1={CY} x2={CX + 88} y2={CY} stroke="#FF8500" strokeWidth="1.2" opacity="0.7" />
      </svg>
      <Bars count={37} sigma={0.32} className={styles.coreBars} meter={meter} live={live} />
    </motion.div>
  )
}
