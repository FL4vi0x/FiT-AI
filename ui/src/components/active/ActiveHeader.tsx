import { motion } from 'motion/react'
import { headerVariants } from '../../motion/activeVariants'
import type { ServiceStatus } from '../../state/useServiceStatus'
import { HondaMark } from './HondaMark'
import styles from '../../screens/ActiveScreen/ActiveScreen.module.css'

export const NAV = [
  { id: 'home', label: 'Home', icon: 'M3 11 12 3l9 8v10h-6v-6H9v6H3z' },
  { id: 'telemetry', label: 'Telemetria', icon: 'M3 18l5-6 4 3 5-8 4 5' },
  { id: 'maintenance', label: 'Manutenção', icon: 'M14 4a5 5 0 0 0-5 6L3 16l3 3 6-6a5 5 0 0 0 6-5l-3 3-3-1-1-3z' },
  { id: 'history', label: 'Histórico', icon: 'M4 5h16v14H4zM8 10l3 3 5-5' },
  { id: 'settings', label: 'Configurações', icon: 'M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8zM12 2v3M12 19v3M2 12h3M19 12h3M5 5l2 2M17 17l2 2M19 5l-2 2M7 17l-2 2' },
] as const

const OCTAVE_LABEL: Record<ServiceStatus['octave'], { text: string; tone: 'ok' | 'warn' | 'off' | 'wait' }> = {
  checking: { text: 'Verificando', tone: 'wait' },
  connected: { text: 'Conectado', tone: 'ok' },
  vehicle_link_down: { text: 'Sem veículo', tone: 'warn' },
  unavailable: { text: 'Indisponível', tone: 'off' },
  no_core: { text: 'Sem Core', tone: 'off' },
}

export function systemLine(s: ServiceStatus): string {
  if (s.core === 'checking') return 'Verificando sistema'
  if (s.core === 'offline') return 'Sistema desconectado'
  return s.octave === 'connected' ? 'Sistema Conectado' : 'Sistema parcial'
}

const fmtTime = (ms: number) => new Date(ms).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })
const fmtDate = (ms: number) => new Date(ms).toLocaleDateString('pt-BR', { weekday: 'short', day: 'numeric', month: 'short' }).replace(/\./g, '')

function Chip({ name, text, tone, id }: { name: string; text: string; tone: string; id: string }) {
  return (
    <div className={styles.chip} data-tone={tone} data-testid={id}>
      <span className={styles.chipDot} aria-hidden="true" />
      <span className={styles.chipText}>
        <strong>{name}</strong>
        <span>{text}</span>
      </span>
    </div>
  )
}

/**
 * The top bar. Only Home exists; the other sections are shown disabled (and say "em breve" to assistive technology): there is no
 * fake navigation. The service chips show real checks, never an invented "online".
 */
export function ActiveHeader({ services, now }: { services: ServiceStatus; now: number }) {
  const o = OCTAVE_LABEL[services.octave]
  return (
    <motion.header className={styles.header} variants={headerVariants} data-testid="active-header">
      <div className={styles.brand}>
        <HondaMark height={38} />
        <div className={styles.brandText}>
          <span className={styles.wordmark} role="img" aria-label="Fit AI">
            <span className={styles.fit}>FIT</span> <span className={styles.ai}>AI</span>
          </span>
          <span className={styles.tagline}>VEHICLE INTELLIGENCE SYSTEM</span>
        </div>
        <div className={styles.vehicleInfo}>
          <span>Honda Fit GD (2005)</span>
          <span data-testid="system-line">{systemLine(services)}</span>
        </div>
      </div>
      <nav className={styles.nav} aria-label="Seções">
        {NAV.map((item) => {
          const current = item.id === 'home'
          return (
            <button key={item.id} type="button" className={styles.navItem} aria-current={current ? 'page' : undefined} disabled={!current} data-testid={`nav-${item.id}`}>
              <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round" aria-hidden="true">
                <path d={item.icon} />
              </svg>
              <span>{item.label}</span>
              {!current && <span className={styles.srOnly}>, em breve</span>}
            </button>
          )
        })}
      </nav>
      <div className={styles.right}>
        <Chip id="chip-ollama" name="Ollama" text="Não verificado" tone="wait" />
        <Chip id="chip-octave" name="OCTAVE" text={o.text} tone={o.tone} />
        <time className={styles.clock} dateTime={new Date(now).toISOString()}>
          <strong>{fmtTime(now)}</strong>
          <span>{fmtDate(now)}</span>
        </time>
      </div>
    </motion.header>
  )
}
