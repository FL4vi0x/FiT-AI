import { motion, useReducedMotion } from 'motion/react'
import type { CSSProperties } from 'react'
import type { CoreLink, OctaveLink, TelemetryView } from '../state/store'

export interface SystemCalloutProps {
  core: CoreLink
  octave: OctaveLink
  telemetry: TelemetryView
  align?: 'left' | 'right'
  className?: string
  style?: CSSProperties
}

const LINK: Record<OctaveLink['status'], string> = {
  connected: 'Conectado',
  degraded: 'Sem ligação com o veículo',
  unreachable: 'Fora do ar',
  unknown: 'Ainda não consultado',
}

/**
 * Shown only when there is something to say about the link: a reading could not be taken, or the user asked about the
 * connection. Plain text tied to the ECU/OBD region by a leader; no box.
 */
export function SystemCallout({ core, octave, telemetry, align = 'left', className = '', style }: SystemCalloutProps) {
  const reduce = useReducedMotion()
  const failed = telemetry.phase === 'unavailable'
  const mode = octave.simulated === true ? 'dados simulados' : octave.simulated === false ? 'dados reais' : null
  return (
    <motion.div
      data-testid="callout-system"
      initial={reduce ? false : { opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.2, ease: [0.2, 0.8, 0.2, 1] }}
      style={{ ...style, textAlign: align }}
      className={className}
    >
      <div className="text-[15px] text-ink-soft">OCTAVE</div>
      {failed ? (
        <div data-testid="system-error" className="mt-1">
          <div className="text-[20px] font-light leading-snug text-ink">{telemetry.message}</div>
          <div className="mt-1 font-mono text-[11px] text-ink-dim">{telemetry.code}</div>
        </div>
      ) : (
        <div className="mt-1">
          <div className="text-[20px] font-light leading-snug text-ink">{[LINK[octave.status], mode].filter(Boolean).join(' · ')}</div>
          <div className="mt-1 text-[14px] text-ink-dim">
            {[octave.protocolVersion !== null ? `protocolo v${octave.protocolVersion}` : null, octave.octaveVersion ? `OCTAVE ${octave.octaveVersion}` : null, core.version ? `Core v${core.version}` : null].filter(Boolean).join(' · ')}
          </div>
        </div>
      )}
    </motion.div>
  )
}
