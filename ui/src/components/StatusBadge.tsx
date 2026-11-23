import type { Tone } from '../lib/labels'

const TEXT: Record<Tone, string> = {
  neutral: 'text-ink-soft',
  accent: 'text-fit-gold',
  ok: 'text-ok',
  warn: 'text-warn',
  error: 'text-err',
  dim: 'text-ink-dim',
}

export interface StatusBadgeProps {
  label: string
  tone?: Tone
  /** Leading status dot. */
  dot?: boolean
  /** Blink the dot (something is in progress). */
  pulse?: boolean
  title?: string
  className?: string
  'data-testid'?: string
}

/**
 * A quiet status note: a small dot and a plain sentence, no box, no capitals. It is reserved for the exceptions worth
 * a user's attention (fallback, partial reading, error); confirmations of the normal case are not announced.
 */
export function StatusBadge({ label, tone = 'neutral', dot = false, pulse = false, title, className = '', ...rest }: StatusBadgeProps) {
  return (
    <span title={title} data-tone={tone} data-testid={rest['data-testid']} className={`inline-flex items-center gap-1.5 text-[12px] leading-snug ${TEXT[tone]} ${className}`}>
      {dot && <span aria-hidden className="h-1.5 w-1.5 shrink-0 rounded-full bg-current" style={pulse ? { animation: 'blink 1.1s ease-in-out infinite' } : undefined} />}
      {label}
    </span>
  )
}
