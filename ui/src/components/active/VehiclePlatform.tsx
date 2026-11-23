import { motion } from 'motion/react'
import { platformVariants } from '../../motion/activeVariants'
import styles from '../../screens/ActiveScreen/ActiveScreen.module.css'

/** The lit circular platform under the car and the thin ring around it (perspective ellipses), plus the soft floor light. */
export function VehiclePlatform() {
  return (
    <motion.svg className={styles.layer} viewBox="0 0 1672 941" variants={platformVariants} aria-hidden="true" focusable="false" data-testid="vehicle-platform">
      <defs>
        <radialGradient id="pf-floor" cx="0.5" cy="0.5" r="0.5">
          <stop offset="0" stopColor="#FF8500" stopOpacity="0.22" />
          <stop offset="0.6" stopColor="#B85A0A" stopOpacity="0.06" />
          <stop offset="1" stopColor="#000" stopOpacity="0" />
        </radialGradient>
        <linearGradient id="pf-ring" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0" stopColor="#FF8500" stopOpacity="0.2" />
          <stop offset="0.5" stopColor="#FFC070" stopOpacity="1" />
          <stop offset="1" stopColor="#FF8500" stopOpacity="0.2" />
        </linearGradient>
      </defs>
      <ellipse cx="836" cy="672" rx="700" ry="150" fill="url(#pf-floor)" />
      <ellipse cx="833" cy="495" rx="424" ry="40" fill="none" stroke="#FF9A1F" strokeWidth="1.6" opacity="0.5" />
      <ellipse cx="836" cy="672" rx="540" ry="92" fill="none" stroke="#FF8500" strokeWidth="1" strokeDasharray="3 9" opacity="0.4" />
      <ellipse cx="836" cy="672" rx="600" ry="108" fill="none" stroke="#FF8500" strokeWidth="1" opacity="0.2" />
      <ellipse cx="836" cy="672" rx="470" ry="74" fill="none" stroke="#FF8500" strokeWidth="1" opacity="0.3" />
      <ellipse cx="836" cy="672" rx="486" ry="64" fill="none" stroke="#FF8500" strokeWidth="14" opacity="0.14" />
      <ellipse cx="836" cy="672" rx="486" ry="64" fill="none" stroke="url(#pf-ring)" strokeWidth="3.4" />
    </motion.svg>
  )
}
