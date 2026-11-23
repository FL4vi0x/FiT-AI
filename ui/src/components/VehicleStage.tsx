import { AnimatePresence } from 'motion/react'
import { useLayoutEffect, useRef, useState, type ReactNode } from 'react'
import { ageSeconds, parseTimestamp, STALE_AFTER_S } from '../lib/format'
import { busPoints, CORE_POS, CORE_SIZE, PANELS, panelLeader, STAGE, zoneAnchor, type PanelId, type ZoneId } from '../lib/vehicleZones'
import type { AppState, Derived } from '../state/store'
import { ConnectionLine } from './ConnectionLine'
import { FitAICore } from './FitAICore'
import { HoloPanel } from './HoloPanel'
import { StatusBadge } from './StatusBadge'
import { SystemCallout } from './SystemCallout'
import { TelemetryCallout } from './TelemetryCallout'
import { VehicleHero } from './VehicleHero'

/** Scales a fixed 1200 x 640 logical stage to the space available, keeping the aspect ratio. */
function StageFrame({ children }: { children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null)
  const [k, setK] = useState(1)
  useLayoutEffect(() => {
    const el = ref.current
    if (!el || typeof ResizeObserver === 'undefined') return
    const fit = (w: number, h: number) => {
      if (w > 0 && h > 0) setK(Math.min(w / STAGE.w, h / STAGE.h))
    }
    fit(el.clientWidth, el.clientHeight)
    const ro = new ResizeObserver(([entry]) => entry && fit(entry.contentRect.width, entry.contentRect.height))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])
  return (
    <div ref={ref} className="relative grid h-full w-full place-items-center overflow-hidden">
      <div data-testid="stage" data-scale={k.toFixed(3)} className="relative" style={{ width: STAGE.w * k, height: STAGE.h * k }}>
        <div className="absolute left-0 top-0" style={{ width: STAGE.w, height: STAGE.h, transform: `scale(${k})`, transformOrigin: 'top left' }}>
          {children}
        </div>
      </div>
    </div>
  )
}

// Display scales of the tracks. They are NOT technical limits: the system has no approved normal/alert thresholds.
const SCALE = {
  rpm: { label: 'Rotação', unit: 'rpm', min: 0, max: 8000, decimals: 0 },
  speed: { label: 'Velocidade', unit: 'km/h', min: 0, max: 200, decimals: 0 },
  temp: { label: 'Temperatura do motor', unit: '°C', min: 40, max: 130, decimals: 0 },
} as const

export interface VehicleStageProps {
  derived: Derived
  state: AppState
  nowMs: number
}

export function VehicleStage({ derived, state, nowMs }: VehicleStageProps) {
  const ready = state.telemetry.phase === 'ready' ? state.telemetry : null
  const takenAt = ready ? parseTimestamp(ready.reading.timestamp, ready.at) : 0
  const stale = ready ? ageSeconds(takenAt, nowMs) > STALE_AFTER_S : false
  const busy = derived.mode === 'thinking' || derived.mode === 'scanning'
  const place = (id: PanelId) => ({ position: 'absolute' as const, left: PANELS[id].rect.x, top: PANELS[id].rect.y, width: PANELS[id].rect.w })

  const value = (id: 'rpm' | 'speed' | 'temp'): number | null => {
    if (!ready) return null
    return id === 'rpm' ? ready.reading.rpm : id === 'speed' ? ready.reading.speed_kmh : ready.reading.coolant_temp_c
  }

  return (
    <StageFrame>
      <VehicleHero activeZones={derived.zones} faultyZones={derived.faulty} scanning={derived.mode === 'scanning'} offline={derived.mode === 'offline'} />

      {/* hairline leaders; and, while the core works, faint links from it to the modules */}
      <svg className="pointer-events-none absolute inset-0 h-full w-full" viewBox={`0 0 ${STAGE.w} ${STAGE.h}`} aria-hidden>
        <AnimatePresence>
          {busy &&
            (['cabin', 'powertrain', 'cooling', 'motion'] as ZoneId[]).map((z, i) => (
              <ConnectionLine key={`bus-${z}`} testId={`bus-${z}`} points={busPoints(zoneAnchor(z))} tone="dim" delay={i * 0.08} duration={0.5} />
            ))}
          {derived.panels.map((id, i) => {
            const missing = id !== 'system' && value(id) === null
            const failed = id === 'system' && state.telemetry.phase === 'unavailable'
            return <ConnectionLine key={`leader-${id}`} testId={`leader-${id}`} points={panelLeader(id)} tone={failed ? 'dim' : missing ? 'warn' : 'accent'} dashed={missing || failed} delay={i * 0.08} />
          })}
        </AnimatePresence>
      </svg>

      <div className="absolute" style={{ left: CORE_POS.x - CORE_SIZE / 2, top: CORE_POS.y - CORE_SIZE / 2 }}>
        <FitAICore state={derived.core} size={CORE_SIZE} />
      </div>

      <AnimatePresence>
        {derived.panels.includes('system') && <SystemCallout key="system" core={state.core} octave={state.octave} telemetry={state.telemetry} align={PANELS.system.align} style={place('system')} />}
        {ready &&
          (['rpm', 'speed', 'temp'] as const).map((id) =>
            derived.panels.includes(id) ? <TelemetryCallout key={id} testId={`callout-${id}`} {...SCALE[id]} value={value(id)} stale={stale} style={place(id)} /> : null,
          )}
      </AnimatePresence>

      {derived.mode === 'offline' && (
        <div className="absolute" style={{ left: 390, top: 288, width: 420 }}>
          <HoloPanel data-testid="offline-banner" tone="neutral" title="Fit AI Core offline" badge={<StatusBadge label="sem conexão" tone="error" dot pulse />}>
            <p className="m-0 text-[15px] leading-snug text-ink-soft">A interface continua tentando e volta sozinha quando o Core estiver no ar. Nenhum dado é exibido enquanto isso.</p>
          </HoloPanel>
        </div>
      )}
    </StageFrame>
  )
}
