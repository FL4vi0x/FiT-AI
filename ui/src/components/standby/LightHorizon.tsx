import { motion } from 'motion/react'
import { HORIZON, SIDE_LINES } from './geometry'
import { horizonVariants, poolVariants, sideLineVariants } from '../../motion/variants'

const { x, y, coreHalfWidth, glowHalfWidth, poolDepth } = HORIZON
const box = { transformBox: 'fill-box' as const, transformOrigin: 'center' }

function SideLine({ id, x0, x1, peakX }: { id: string; x0: number; x1: number; peakX: number }) {
  const peak = (peakX - x0) / (x1 - x0)
  return (
    <motion.g variants={sideLineVariants} style={box}>
      <linearGradient id={id} gradientUnits="userSpaceOnUse" x1={x0} y1="0" x2={x1} y2="0">
        <stop offset="0" stopColor="#FFB517" stopOpacity="0" />
        <stop offset={peak} stopColor="#FFB517" stopOpacity="0.9" />
        <stop offset="1" stopColor="#FF8500" stopOpacity="0" />
      </linearGradient>
      <rect x={x0} y={SIDE_LINES.y - 4} width={x1 - x0} height={8} fill={`url(#${id})`} opacity={0.1} />
      <rect x={x0} y={SIDE_LINES.y - SIDE_LINES.thickness / 2} width={x1 - x0} height={SIDE_LINES.thickness} fill={`url(#${id})`} />
    </motion.g>
  )
}

/** The amber light under the identity (core, glow, the pool on the floor) and the two thin side lines at the wordmark. */
export function LightHorizon({ className }: { className?: string }) {
  return (
    <>
      <defs>
        <radialGradient id="hz-core" cx="0.5" cy="0.5" r="0.5">
          <stop offset="0" stopColor="#FEEDB4" />
          <stop offset="0.35" stopColor="#FFB517" stopOpacity="0.85" />
          <stop offset="1" stopColor="#FF8500" stopOpacity="0" />
        </radialGradient>
        <radialGradient id="hz-glow" cx="0.5" cy="0.5" r="0.5">
          <stop offset="0" stopColor="#FF8500" stopOpacity="0.8" />
          <stop offset="1" stopColor="#FF8500" stopOpacity="0" />
        </radialGradient>
        <radialGradient id="hz-pool" cx="0.5" cy="0" r="0.5">
          <stop offset="0" stopColor="#FF8500" stopOpacity="0.3" />
          <stop offset="0.4" stopColor="#B85A0A" stopOpacity="0.09" />
          <stop offset="1" stopColor="#000" stopOpacity="0" />
        </radialGradient>
      </defs>
      <SideLine id="sl-left" {...SIDE_LINES.left} />
      <SideLine id="sl-right" {...SIDE_LINES.right} />
      <motion.g variants={poolVariants}>
        <g className={className}>
          <path d={`M ${x - glowHalfWidth * 2} ${y} A ${glowHalfWidth * 2} ${poolDepth * 2} 0 0 0 ${x + glowHalfWidth * 2} ${y} Z`} fill="url(#hz-pool)" />
        </g>
      </motion.g>
      <motion.g variants={horizonVariants} style={box}>
        <g className={className}>
          <ellipse cx={x} cy={y} rx={glowHalfWidth} ry={20} fill="url(#hz-glow)" />
          <ellipse cx={x} cy={y} rx={coreHalfWidth * 0.8} ry={11} fill="url(#hz-glow)" />
          <ellipse cx={x} cy={y} rx={coreHalfWidth * 0.62} ry={4.5} fill="url(#hz-core)" />
        </g>
      </motion.g>
    </>
  )
}
