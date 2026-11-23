import { motion } from 'motion/react'
import { ringsVariants } from '../../motion/activeVariants'
import styles from '../../screens/ActiveScreen/ActiveScreen.module.css'

const CX = 836
const CY = 470
const polar = (r: number, deg: number) => [CX + r * Math.cos((deg * Math.PI) / 180), CY + r * Math.sin((deg * Math.PI) / 180)] as const
const arc = (r: number, a0: number, a1: number) => {
  const [x0, y0] = polar(r, a0)
  const [x1, y1] = polar(r, a1)
  return `M ${x0.toFixed(1)} ${y0.toFixed(1)} A ${r} ${r} 0 0 ${a1 > a0 ? 1 : 0} ${x1.toFixed(1)} ${y1.toFixed(1)}`
}

/** The big side rings of the HUD: the Standby arcs, reborn as circles around the stage. Mirrored for the right side. */
export function AmbientRings() {
  const side = (mirror: boolean) => (
    <g key={mirror ? 'r' : 'l'} transform={mirror ? `translate(${2 * CX} 0) scale(-1 1)` : undefined}>
      <path d={arc(640, 128, 232)} fill="none" stroke="#FF8500" strokeWidth="1.4" opacity="0.5" />
      <path d={arc(700, 135, 225)} fill="none" stroke="#FF8500" strokeWidth="1" opacity="0.28" />
      <path d={arc(585, 150, 215)} fill="none" stroke="#FF8500" strokeWidth="1.2" opacity="0.4" />
      {/* the bright short segments */}
      {[
        [205, 213],
        [183, 188],
      ].map(([a, b]) => (
        <g key={a}>
          <path d={arc(572, a!, b!)} fill="none" stroke="#FF8500" strokeWidth="18" opacity="0.14" />
          <path d={arc(572, a!, b!)} fill="none" stroke="#FF9A1F" strokeWidth="8" opacity="0.9" />
        </g>
      ))}
      <ellipse cx="150" cy="382" rx="26" ry="6" fill="#FF9A1F" opacity="0.8" />
      <ellipse cx="150" cy="382" rx="60" ry="14" fill="#FF8500" opacity="0.14" />
    </g>
  )
  return (
    <motion.svg className={styles.layer} viewBox="0 0 1672 941" variants={ringsVariants} aria-hidden="true" focusable="false" data-testid="ambient-rings">
      {side(false)}
      {side(true)}
    </motion.svg>
  )
}
