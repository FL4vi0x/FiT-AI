import { motion } from 'motion/react'
import { waveformVariants } from '../../motion/activeVariants'
import { errorText } from '../../lib/labels'
import { ageSeconds, fmtAge, fmtNumber, parseTimestamp, STALE_AFTER_S } from '../../lib/format'
import type { ServiceStatus } from '../../state/useServiceStatus'
import type { TelemetryView } from '../../state/useTelemetry'
import { OCTAVE_LABEL } from './ActiveHeader'
import styles from '../../screens/ActiveScreen/ActiveScreen.module.css'

const ROWS = [
  { id: 'rpm', label: 'Rotação', unit: 'rpm', pick: (r: { rpm: number | null }) => r.rpm },
  { id: 'speed', label: 'Velocidade', unit: 'km/h', pick: (r: { speed_kmh: number | null }) => r.speed_kmh },
  { id: 'coolant', label: 'Arrefecimento', unit: '°C', pick: (r: { coolant_temp_c: number | null }) => r.coolant_temp_c },
] as const

/** Integers stay integers; anything else is shown with one decimal. The number is the Core's, only formatted. */
const show = (v: number | null) => (v === null ? '—' : fmtNumber(v, Number.isInteger(v) ? 0 : 1))

function origin(simulated: boolean | null): { text: string; tone: 'sim' | 'real' | 'unknown' } {
  if (simulated === true) return { text: 'DADOS SIMULADOS', tone: 'sim' }
  if (simulated === false) return { text: 'DADOS DO VEÍCULO', tone: 'real' }
  return { text: 'ORIGEM NÃO INFORMADA', tone: 'unknown' }
}

/**
 * The three readings the Core really provides (RPM, speed in km/h, coolant temperature) and the state of the connection. The
 * origin badge is always on screen: while the source is the OCTAVE simulator it reads DADOS SIMULADOS. There is no judgement
 * ("normal", "high", "warning"), no battery, tyre or fault data: the Core has none, so none is shown. A missing value is an em
 * dash, never zero, and a reading older than the Core's own freshness limit is marked as out of date.
 */
export function TelemetryReadout({ view, services, now }: { view: TelemetryView; services: ServiceStatus; now: number }) {
  const reading = view.kind === 'ok' ? view.reading : null
  const o = origin(reading ? reading.simulated : services.simulated)
  const age = reading ? ageSeconds(parseTimestamp(reading.timestamp, view.kind === 'ok' ? view.receivedAt : now), now) : null
  const stale = age !== null && age > STALE_AFTER_S
  const link = OCTAVE_LABEL[services.octave]
  const missing = reading?.missing ?? []

  return (
    <motion.section className={styles.telemetry} variants={waveformVariants} aria-label={`Telemetria. ${o.text.toLowerCase()}`} data-testid="telemetry" data-origin={o.tone} data-stale={stale || undefined}>
      <header className={styles.telemetryHead}>
        <span className={styles.telemetryTitle}>TELEMETRIA</span>
        <span className={styles.originBadge} data-tone={o.tone} data-testid="origin-badge">
          {o.text}
        </span>
      </header>
      <dl className={styles.readings}>
        {ROWS.map((r) => {
          const value = reading ? r.pick(reading as never) : null
          const absent = value === null
          return (
            <div key={r.id} className={styles.reading} data-testid={`reading-${r.id}`} data-absent={absent || undefined}>
              <dt>{r.label}</dt>
              <dd>
                <strong className={stale ? styles.dimValue : undefined}>{show(value)}</strong>
                {!absent && <span className={styles.unit}>{r.unit}</span>}
                {absent && <span className={styles.srOnly}>, indisponível</span>}
              </dd>
            </div>
          )
        })}
      </dl>
      <p className={styles.telemetryNote} data-testid="telemetry-note" data-tone={view.kind === 'error' || stale ? 'warn' : link.tone}>
        {view.kind === 'error'
          ? `Sem leitura: ${errorText(view.code, view.message)}`
          : view.kind === 'idle' || view.kind === 'loading'
            ? 'Aguardando a primeira leitura'
            : stale
              ? `Leitura desatualizada (${fmtAge(age ?? 0)})`
              : missing.length > 0
                ? `Leitura parcial. Indisponível: ${missing.map((m) => ({ rpm: 'rotação', speed_kmh: 'velocidade', coolant_temp_c: 'arrefecimento' })[m as 'rpm'] ?? m).join(', ')}`
                : `Conexão: ${link.text.toLowerCase()} · ${age !== null ? fmtAge(age) : ''}`}
      </p>
    </motion.section>
  )
}
