import { fmtClock } from '../lib/format'
import type { FeedEvent } from '../state/store'

const LEVEL = {
  info: 'text-ink-soft',
  ok: 'text-ink-soft',
  warn: 'text-warn',
  error: 'text-err',
} as const

export interface ActivityFeedProps {
  events: FeedEvent[]
  /** How many of the latest events are shown. */
  max?: number
  className?: string
}

/** What the system has really been doing (every line is a real call or a real state change). It lives in the status popover. */
export function ActivityFeed({ events, max = 8, className = '' }: ActivityFeedProps) {
  const shown = events.slice(-max)
  return (
    <div data-testid="activity-feed" role="log" aria-label="Atividade do sistema" className={`text-[12px] leading-relaxed ${className}`}>
      {shown.length === 0 && <p className="m-0 text-ink-dim">Nada ainda.</p>}
      <ul className="m-0 list-none space-y-0.5 p-0">
        {shown.map((e) => (
          <li key={e.id} className="flex gap-3">
            <span className="shrink-0 tabular-nums text-ink-dim">{fmtClock(e.at)}</span>
            <span className="w-[5.5rem] shrink-0 text-ink-dim">{e.tag.toLowerCase()}</span>
            <span className={`min-w-0 ${LEVEL[e.level]}`}>{e.text}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}
