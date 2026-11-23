import { toolMeta } from '../lib/labels'

export interface ToolBadgeProps {
  /** Backend tool name, e.g. `get_vehicle_telemetry`. */
  name: string
  className?: string
}

/** A tool the assistant used on this turn. Every tool of the Core only reads, and it says so in words. */
export function ToolBadge({ name, className = '' }: ToolBadgeProps) {
  const meta = toolMeta(name)
  return (
    <span title={meta.hint} data-testid="tool-badge" data-tool={name} className={`inline-flex items-center gap-1.5 text-[13px] text-ink-soft ${className}`}>
      <svg aria-hidden width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.2" className="shrink-0 text-fit-gold">
        <path d="M1.5 6h2.2l1.2-3.4 1.7 6.8 1.3-3.4h1.6" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      {meta.label}
      <span className="text-ink-dim">· somente leitura</span>
    </span>
  )
}
