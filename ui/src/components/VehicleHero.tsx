import { motion, useReducedMotion } from 'motion/react'
import { CAR, SCAN_NODES, STAGE, WHEEL_FRONT, WHEEL_REAR, ZONES, type ZoneId } from '../lib/vehicleZones'
import { VehicleHighlightZone } from './VehicleHighlightZone'

// Honda Fit (GD1, 2005) in side view, front to the right, drawn in a 1000 x 440 box. Proportions follow the car: wheelbase
// 2450 mm = 588 units (scale 0.24 units/mm), short bonnet, steep windscreen, tall roof, near-vertical tailgate, 175/65 R14.
// The wheel arches are circular arcs (r = 84) around the axle centres (190, 322) and (778, 322); the ground is y = 392.
const BODY =
  'M 111.5 352 L 66 352 Q 44 350 41 326 L 38 286 Q 38 262 46 240 L 92 112 Q 100 56 124 38 Q 320 16 520 24 ' +
  'Q 550 26 566 38 L 770 186 Q 782 197 806 200 L 912 214 Q 946 220 956 252 L 962 304 Q 964 338 944 349 L 930 352 ' +
  'L 856.5 352 A 84 84 0 1 0 699.5 352 L 268.5 352 A 84 84 0 1 0 111.5 352 Z'

// side glass (daylight opening): A-pillar, roof edge, D-pillar, beltline
const GLASS = 'M 742 188 L 582 48 L 530 44 L 150 46 L 112 74 L 124 150 L 140 190 Z'

function Wheel({ cx, cy }: { cx: number; cy: number }) {
  const spokes = Array.from({ length: 5 }, (_, i) => {
    const a = ((i * 72 - 90) * Math.PI) / 180
    return { x1: cx + 14 * Math.cos(a), y1: cy + 14 * Math.sin(a), x2: cx + 46 * Math.cos(a), y2: cy + 46 * Math.sin(a) }
  })
  return (
    <g fill="none" stroke="var(--car-line)">
      <circle cx={cx} cy={cy} r={68} fill="#0B0B0F" fillOpacity={0.9} strokeWidth={1.4} />
      <circle cx={cx} cy={cy} r={48} strokeWidth={1} strokeOpacity={0.55} />
      {spokes.map((s, i) => (
        <line key={i} x1={s.x1} y1={s.y1} x2={s.x2} y2={s.y2} strokeWidth={1} strokeOpacity={0.5} strokeLinecap="round" />
      ))}
      <circle cx={cx} cy={cy} r={9} strokeWidth={1} strokeOpacity={0.7} />
    </g>
  )
}

export interface VehicleHeroProps {
  /** Zones lit up because their information is being scanned or presented. */
  activeZones: ZoneId[]
  /** Zones with no data to show (grey, dashed). */
  faultyZones: ZoneId[]
  /** A real telemetry request is in flight: a sweep over the body plus pulsing points on the regions. */
  scanning: boolean
  /** The Core is unreachable: the car is shown dark and still. */
  offline: boolean
}

/** The subject of the product: a fine outline of the owner's car. A single SVG layer in STAGE coordinates. */
export function VehicleHero({ activeZones, faultyZones, scanning, offline }: VehicleHeroProps) {
  const reduce = useReducedMotion()
  const fade = (delay: number) => ({ initial: reduce ? false : { opacity: 0 }, animate: { opacity: 1 }, transition: { duration: 0.7, delay } }) as const
  return (
    <svg
      data-testid="vehicle-hero"
      data-scanning={scanning}
      data-offline={offline}
      className="absolute inset-0 h-full w-full"
      viewBox={`0 0 ${STAGE.w} ${STAGE.h}`}
      role="img"
      aria-label="Honda Fit 2005 em vista lateral, desenho técnico"
    >
      <defs>
        <linearGradient id="bodyFill" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#FFD6A0" stopOpacity="0.06" />
          <stop offset="1" stopColor="#FFD6A0" stopOpacity="0" />
        </linearGradient>
        <linearGradient id="beamGrad" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0" stopColor="#FFB347" stopOpacity="0" />
          <stop offset="1" stopColor="#FFC76A" stopOpacity="0.5" />
        </linearGradient>
        <radialGradient id="groundGlow" cx="0.5" cy="0.5" r="0.5">
          <stop offset="0" stopColor="#FF7A00" stopOpacity="0.16" />
          <stop offset="1" stopColor="#FF7A00" stopOpacity="0" />
        </radialGradient>
        <clipPath id="carClip">
          <path d={BODY} />
        </clipPath>
      </defs>

      <g transform={`translate(${CAR.x} ${CAR.y}) scale(${CAR.scale})`} style={{ transition: 'opacity 0.6s', opacity: offline ? 0.3 : 1 }}>
        {/* the car stands on a soft pool of warm light, not on a drawn line */}
        <ellipse cx={500} cy={394} rx={470} ry={20} fill="url(#groundGlow)" />

        <motion.path d={BODY} fill="url(#bodyFill)" {...fade(0.5)} />
        <motion.path
          d={BODY}
          fill="none"
          stroke="var(--car-line)"
          strokeWidth={1.6}
          strokeLinejoin="round"
          initial={reduce ? false : { pathLength: 0 }}
          animate={{ pathLength: 1 }}
          transition={{ duration: 1.5, ease: [0.4, 0, 0.2, 1] }}
        />

        {/* greenhouse, door cuts and lamps: just enough detail to read as a Fit and not as a generic hatchback */}
        <motion.g {...fade(0.9)} fill="none" stroke="var(--car-line)" strokeOpacity={0.5} strokeWidth={1} strokeLinejoin="round" strokeLinecap="round">
          <path d={GLASS} strokeOpacity={0.55} />
          <path d="M 432 46 L 434 190 M 269 46 L 270 190" strokeOpacity={0.4} />
          <path d="M 130 190 L 745 190" strokeOpacity={0.45} />
          <path d="M 436 192 L 436 346 M 272 192 L 272 346 M 748 198 L 752 346" strokeOpacity={0.3} />
          <rect x={392} y={212} width={30} height={7} rx={3.5} strokeOpacity={0.4} />
          <rect x={650} y={212} width={30} height={7} rx={3.5} strokeOpacity={0.4} />
          <path d="M 724 190 L 706 174 Q 698 172 696 180 L 704 192 Z" strokeOpacity={0.45} />
          <path d="M 902 220 L 948 237 Q 957 245 955 259 L 912 257 Z" strokeOpacity={0.6} />
          <path d="M 46 240 L 67 245 L 90 156 L 73 150 Z" strokeOpacity={0.55} />
        </motion.g>

        <Wheel cx={WHEEL_REAR.x} cy={WHEEL_REAR.y} />
        <Wheel cx={WHEEL_FRONT.x} cy={WHEEL_FRONT.y} />

        {(Object.keys(ZONES) as ZoneId[]).map((id) => (
          <VehicleHighlightZone key={id} zone={ZONES[id]} active={activeZones.includes(id)} faulty={faultyZones.includes(id)} />
        ))}

        {/* the one-time "waking up" pass when the screen opens (it ends off screen: no cost afterwards) */}
        {!reduce && (
          <g clipPath="url(#carClip)" pointerEvents="none">
            <motion.rect y={0} width={130} height={440} fill="url(#beamGrad)" initial={{ x: -150 }} animate={{ x: 1020 }} transition={{ duration: 1.4, delay: 1.2, ease: 'easeInOut' }} />
          </g>
        )}

        {/* scanning: a real telemetry request is in flight */}
        {scanning && (
          <g data-testid="scan-layer" pointerEvents="none">
            <g clipPath="url(#carClip)">
              <motion.rect
                y={0}
                width={130}
                height={440}
                fill="url(#beamGrad)"
                initial={{ x: -150 }}
                animate={{ x: 1020 }}
                transition={{ duration: reduce ? 0.01 : 1.4, repeat: Infinity, ease: 'easeInOut' }}
              />
            </g>
            {SCAN_NODES.map((n, i) => (
              <circle key={i} cx={n.x} cy={n.y} r={3.6} fill="var(--sun)" style={{ opacity: 0.85, animation: `breathe 1.2s ease-in-out ${(i * 0.14).toFixed(2)}s infinite` }} />
            ))}
          </g>
        )}

        <motion.text {...fade(1.3)} x={500} y={436} textAnchor="middle" fontSize="14" fill="var(--ink-dim)" style={{ fontFamily: 'inherit' }}>
          Honda Fit LX · 2005
        </motion.text>
      </g>
    </svg>
  )
}
