import { motion, useReducedMotion } from 'motion/react'
import { fmtNumber } from '../lib/format'

export interface TelemetryGaugeProps {
  label: string
  unit: string
  /** `null` = the source did not provide this field: an empty track, never a zero. */
  value: number | null
  /** Display scale of the track. It is NOT a technical limit: the system has no approved normal/alert thresholds. */
  min: number
  max: number
  decimals?: number
  /** Reading older than the freshness limit: drawn dimmed. */
  stale?: boolean
}

/**
 * A hairline track under a reading: how far along its display scale the value is, nothing more. It is deliberately neutral:
 * no "warning" colour by value, because judging a value as normal or high would claim thresholds that were never approved
 * (the Core's verifier forbids those judgements for the same reason).
 */
export function TelemetryGauge({ label, unit, value, min, max, decimals = 0, stale = false }: TelemetryGaugeProps) {
  const reduce = useReducedMotion()
  const has = value !== null && !Number.isNaN(value)
  const frac = has ? Math.min(1, Math.max(0, (value - min) / (max - min))) : 0
  const a11y = has
    ? { role: 'meter' as const, 'aria-label': `${label}: ${fmtNumber(value, decimals)} ${unit}`, 'aria-valuenow': value, 'aria-valuemin': min, 'aria-valuemax': max }
    : { role: 'img' as const, 'aria-label': `${label}: indisponível` }
  return (
    <div data-testid="telemetry-gauge" data-available={has} className={`h-[2px] w-full overflow-hidden rounded-full bg-white/[0.09] ${stale ? 'opacity-50' : ''}`} {...a11y}>
      {has && (
        <motion.div
          className="h-full rounded-full bg-fit-amber"
          initial={reduce ? false : { width: 0 }}
          animate={{ width: `${Math.max(frac, 0.01) * 100}%` }}
          transition={{ duration: 0.7, ease: [0.2, 0.8, 0.2, 1] }}
        />
      )}
    </div>
  )
}
