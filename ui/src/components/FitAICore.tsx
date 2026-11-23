import type { CSSProperties } from 'react'
import type { CoreState } from '../state/store'

const LABEL: Record<CoreState, string> = {
  idle: 'em espera',
  scanning: 'consultando o veículo',
  thinking: 'pensando',
  responding: 'respondendo',
  offline: 'offline',
}

const COLOR: Record<CoreState, string> = {
  idle: '#FF8F1F',
  scanning: '#FFB347',
  thinking: '#FF8F1F',
  responding: '#FFC76A',
  offline: '#6B7280',
}

export interface FitAICoreProps {
  state: CoreState
  /** Pixel size of the core. */
  size?: number
  className?: string
}

/**
 * The "brain": a thin ring and a light, set on the dashboard where the head unit lives. It carries no label; the state is
 * read from its motion alone (dim and still / breathing / one ripple per second / a single ripple / grey). The state machine
 * lives in CSS (`data-state`), so the motion costs nothing per frame in JavaScript.
 */
export function FitAICore({ state, size = 44, className = '' }: FitAICoreProps) {
  const style = { '--c': COLOR[state], width: size, height: size } as CSSProperties
  return (
    <div data-testid="fit-ai-core" data-state={state} role="status" aria-label={`Fit AI: ${LABEL[state]}`} className={`core ${className}`} style={style}>
      <svg viewBox="0 0 44 44" width={size} height={size} style={{ overflow: 'visible' }} aria-hidden>
        <circle data-layer="ripple" cx="22" cy="22" r="14" fill="none" stroke="var(--c)" strokeWidth="1" />
        <circle cx="22" cy="22" r="17" fill="none" stroke="var(--c)" strokeOpacity={state === 'offline' ? 0.3 : 0.4} strokeWidth="1" />
        <circle data-layer="dot" cx="22" cy="22" r="5.5" fill="var(--c)" />
      </svg>
    </div>
  )
}
