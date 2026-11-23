import { motion, useReducedMotion } from 'motion/react'
import type { CSSProperties } from 'react'
import { fmtNumber } from '../lib/format'
import { TelemetryGauge } from './TelemetryGauge'

export interface TelemetryCalloutProps {
  testId: string
  label: string
  unit: string
  value: number | null
  min: number
  max: number
  decimals?: number
  /** Older than the freshness limit: the number is dimmed (the provenance line says how old it is). */
  stale: boolean
  className?: string
  style?: CSSProperties
}

/**
 * One reading, floating next to its region of the car and tied to it by a hairline leader (drawn by the stage). A label, a
 * large light numeral, a unit and a hairline scale: no box, no badge. Where the number comes from (simulated or not, how
 * old) is said once for all readings, in the provenance line, not repeated here.
 */
export function TelemetryCallout({ testId, label, unit, value, min, max, decimals = 0, stale, className = '', style }: TelemetryCalloutProps) {
  const reduce = useReducedMotion()
  const missing = value === null
  return (
    <motion.div
      data-testid={testId}
      data-stale={stale}
      data-missing={missing}
      initial={reduce ? false : { opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.2, ease: [0.2, 0.8, 0.2, 1] }}
      style={style}
      className={className}
    >
      <div className="text-[15px] text-ink-soft">{label}</div>
      {missing ? (
        <div className="mt-1">
          <span className="font-display text-[56px] font-light leading-none text-ink-dim">—</span>
          <div className="mt-1 text-[14px] text-ink-dim">indisponível</div>
        </div>
      ) : (
        <div className="mt-1 flex items-baseline gap-2">
          <span data-testid={`${testId}-value`} className={`font-display text-[64px] font-light leading-none tabular-nums tracking-tight ${stale ? 'text-ink-dim' : 'text-fit-gold'}`}>
            {fmtNumber(value, decimals)}
          </span>
          <span className="text-[16px] text-ink-dim">{unit}</span>
        </div>
      )}
      <div className="mt-3 w-[132px]">
        <TelemetryGauge label={label} unit={unit} value={value} min={min} max={max} decimals={decimals} stale={stale} />
      </div>
    </motion.div>
  )
}
