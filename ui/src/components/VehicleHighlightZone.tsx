import { motion } from 'motion/react'
import type { ZoneDef } from '../lib/vehicleZones'

export interface VehicleHighlightZoneProps {
  zone: ZoneDef
  /** The zone is part of what the HUD is presenting or scanning. */
  active: boolean
  /** The region has no data to show: a grey dashed hairline. */
  faulty?: boolean
}

/**
 * The region of the car that a reading belongs to: a soft warm fill and a solid hairline, lit only while its information is
 * on screen. It carries no painted label (the name is its tooltip): the readout next to it already names the quantity.
 * Drawn in CAR coordinates (inside the car group).
 */
export function VehicleHighlightZone({ zone, active, faulty = false }: VehicleHighlightZoneProps) {
  const show = active || faulty
  const stroke = faulty ? 'rgba(237,242,247,0.35)' : 'rgba(255,122,0,0.55)'
  const fill = faulty ? 'rgba(237,242,247,0.035)' : 'rgba(255,122,0,0.06)'
  const dash = faulty ? '4 5' : undefined
  return (
    <motion.g data-testid={`zone-${zone.id}`} data-active={show} data-faulty={faulty} initial={false} animate={{ opacity: show ? 1 : 0 }} transition={{ duration: 0.3 }} pointerEvents="none">
      <title>{zone.label}</title>
      {zone.shapes.map((s, i) =>
        s.kind === 'rect' ? (
          <rect key={i} x={s.x} y={s.y} width={s.w} height={s.h} rx={s.r} fill={fill} stroke={stroke} strokeWidth={1.5} strokeDasharray={dash} />
        ) : (
          <circle key={i} cx={s.cx} cy={s.cy} r={s.r} fill={fill} stroke={stroke} strokeWidth={1.5} strokeDasharray={dash} />
        ),
      )}
    </motion.g>
  )
}
