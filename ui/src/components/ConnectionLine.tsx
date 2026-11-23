import { motion, useReducedMotion } from 'motion/react'
import { toPath, type Pt } from '../lib/vehicleZones'

// hairline colour / end-dot colour per tone: structure is neutral, the dot on the region is the only warm touch
const LINE = {
  accent: 'rgba(237,242,247,0.42)',
  warn: 'rgba(245,158,11,0.6)',
  error: 'rgba(239,68,68,0.6)',
  dim: 'rgba(237,242,247,0.2)',
} as const
const DOT = { accent: 'var(--orange)', warn: 'var(--warn)', error: 'var(--err)', dim: 'rgba(237,242,247,0.35)' } as const

export interface ConnectionLineProps {
  points: Pt[]
  tone?: keyof typeof LINE
  /** Dashed: the link points at something that has no data. */
  dashed?: boolean
  /** Seconds before the line starts drawing. */
  delay?: number
  /** Draw time in seconds. */
  duration?: number
  testId?: string
}

/**
 * A hairline leader that draws itself from the reading to its region of the car and ends in a small dot on the region. It
 * must be rendered inside an <svg> in STAGE coordinates (and inside AnimatePresence for the exit).
 */
export function ConnectionLine({ points, tone = 'accent', dashed = false, delay = 0, duration = 0.26, testId }: ConnectionLineProps) {
  const reduce = useReducedMotion()
  const d = toPath(points)
  const end = points[points.length - 1]
  return (
    <motion.g data-testid={testId} initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.16, delay }}>
      {dashed ? (
        // the draw-on animation drives stroke-dasharray (pathLength), which would erase the dashes: dashed links just fade in
        <path d={d} fill="none" stroke={LINE[tone]} strokeWidth={1} strokeLinejoin="round" strokeDasharray="4 5" />
      ) : (
        <motion.path
          d={d}
          fill="none"
          stroke={LINE[tone]}
          strokeWidth={1}
          strokeLinejoin="round"
          initial={reduce ? false : { pathLength: 0 }}
          animate={{ pathLength: 1 }}
          transition={{ duration, delay: delay + 0.12, ease: [0.2, 0.8, 0.2, 1] }}
        />
      )}
      {end && (
        <motion.circle
          cx={end.x}
          cy={end.y}
          r={3.4}
          fill={DOT[tone]}
          initial={reduce ? false : { opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.12, delay }}
        />
      )}
    </motion.g>
  )
}
