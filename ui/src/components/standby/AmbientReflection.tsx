import { motion } from 'motion/react'
import { FLOOR } from './geometry'
import { WordmarkGlyphs } from './FitAiWordmark'
import { reflectionVariants } from '../../motion/variants'

/** Soft floor reflections: the wordmark mirrored about the floor line (faded out with depth) and a streak under each outer arc. */
export function AmbientReflection() {
  const streak = (cx: number, id: string) => (
    <rect key={id} x={cx - FLOOR.streakWidth / 2} y={FLOOR.streakY0} width={FLOOR.streakWidth} height={FLOOR.streakY1 - FLOOR.streakY0} fill="url(#rf-streak)" />
  )
  return (
    <motion.g variants={reflectionVariants}>
      <defs>
        <linearGradient id="rf-fade" gradientUnits="userSpaceOnUse" x1="0" y1={FLOOR.y} x2="0" y2={FLOOR.y + 180}>
          <stop offset="0" stopColor="#fff" stopOpacity="0.6" />
          <stop offset="1" stopColor="#fff" stopOpacity="0" />
        </linearGradient>
        <mask id="rf-mask" maskUnits="userSpaceOnUse" x="0" y={FLOOR.y} width="1672" height="200">
          <rect x="0" y={FLOOR.y} width="1672" height="200" fill="url(#rf-fade)" />
        </mask>
        <linearGradient id="rf-streak" gradientUnits="userSpaceOnUse" x1="0" y1={FLOOR.streakY0} x2="0" y2={FLOOR.streakY1}>
          <stop offset="0" stopColor="#FF8500" stopOpacity="0" />
          <stop offset={(FLOOR.streakPeakY - FLOOR.streakY0) / (FLOOR.streakY1 - FLOOR.streakY0)} stopColor="#FF8500" stopOpacity="0.36" />
          <stop offset="1" stopColor="#FF8500" stopOpacity="0" />
        </linearGradient>
        <filter id="rf-blur" x="-5%" y="-20%" width="110%" height="140%">
          <feGaussianBlur stdDeviation="3.5 6" />
        </filter>
      </defs>
      <g mask="url(#rf-mask)" filter="url(#rf-blur)">
        <g transform={`translate(0 ${2 * FLOOR.mirrorY}) scale(1 -1)`}>
          <WordmarkGlyphs id="rf" />
        </g>
      </g>
      {streak(FLOOR.streakLeftX, 'l')}
      {streak(FLOOR.streakRightX, 'r')}
    </motion.g>
  )
}
