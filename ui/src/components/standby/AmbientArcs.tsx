import { motion } from 'motion/react'
import { ARC_INNER_LEFT, ARC_INNER_STOPS, ARC_MIRROR_X, ARC_OUTER_LEFT, ARC_OUTER_STOPS, smoothPath } from './geometry'
import { arcVariants } from '../../motion/variants'

const INNER = smoothPath(ARC_INNER_LEFT)
const OUTER = smoothPath(ARC_OUTER_LEFT)

/** the halo and the glow use the same brightness profile but only in amber, so they never read as a grey band */
const warm = (c: string) => {
  const r = parseInt(c.slice(1, 3), 16)
  return `rgb(${r}, ${Math.round(r * 0.5)}, 0)`
}

const offsetOf = (y: number) => Math.min(1, Math.max(0, (664 - y) / 664))

function Gradient({ id, stops, amber = false }: { id: string; stops: ReadonlyArray<readonly [number, string]>; amber?: boolean }) {
  return (
    <linearGradient id={id} gradientUnits="userSpaceOnUse" x1="0" y1="664" x2="0" y2="0">
      {stops.map(([y, c]) => (
        <stop key={y} offset={offsetOf(y)} stopColor={amber ? warm(c) : c} />
      ))}
    </linearGradient>
  )
}

/** Three stacked strokes: a thin hot core, a soft halo and a wide very faint glow. All use the same measured gradient. */
function Arc({ d, grad, order, core, halo, glow }: { d: string; grad: string; order: number; core: number; halo: number; glow: number }) {
  const common = { d, fill: 'none', variants: arcVariants, custom: order, strokeLinecap: 'round' as const }
  return (
    <>
      {/* the fixed opacity lives on a wrapper: the entrance variants animate each path's own opacity to 1 */}
      <g opacity={0.1}>
        <motion.path {...common} stroke={`url(#${grad}-warm)`} strokeWidth={glow} />
      </g>
      <g opacity={0.2}>
        <motion.path {...common} stroke={`url(#${grad}-warm)`} strokeWidth={halo} />
      </g>
      <motion.path {...common} stroke={`url(#${grad})`} strokeWidth={core} />
    </>
  )
}

/** Left arcs as measured, right ones mirrored about x = 834.5. The `inner` / `outer` group classes carry the idle loops. */
export function AmbientArcs({ innerClass, outerClass }: { innerClass?: string; outerClass?: string }) {
  const sides = [
    { key: 'l', transform: undefined, o: 0 },
    { key: 'r', transform: `translate(${ARC_MIRROR_X} 0) scale(-1 1)`, o: 1 },
  ]
  return (
    <>
      <defs>
        <Gradient id="arc-inner" stops={ARC_INNER_STOPS} />
        <Gradient id="arc-inner-warm" stops={ARC_INNER_STOPS} amber />
        <Gradient id="arc-outer-warm" stops={ARC_OUTER_STOPS} amber />
        <Gradient id="arc-outer" stops={ARC_OUTER_STOPS} />
      </defs>
      <g className={outerClass}>
        {sides.map((s) => (
          <g key={s.key} transform={s.transform}>
            <Arc d={OUTER} grad="arc-outer" order={s.o} core={1.5} halo={6} glow={20} />
          </g>
        ))}
      </g>
      <g className={innerClass}>
        {sides.map((s) => (
          <g key={s.key} transform={s.transform}>
            <Arc d={INNER} grad="arc-inner" order={s.o + 2} core={2.2} halo={8} glow={24} />
          </g>
        ))}
      </g>
    </>
  )
}
