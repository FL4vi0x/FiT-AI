import { motion, useReducedMotion } from 'motion/react'
import type { CSSProperties, ReactNode } from 'react'

export type PanelTone = 'accent' | 'warn' | 'error' | 'neutral'

const BORDER: Record<PanelTone, string> = {
  accent: 'border-white/[0.07]',
  neutral: 'border-white/[0.07]',
  warn: 'border-warn/30',
  error: 'border-err/30',
}

export interface HoloPanelProps {
  title?: ReactNode
  /** Right side of the header. */
  badge?: ReactNode
  tone?: PanelTone
  className?: string
  style?: CSSProperties
  children?: ReactNode
  'data-testid'?: string
}

/**
 * The one surface of the interface: opaque, one luminance step above the background, a hairline border and soft corners.
 * No glass, no glow, no frame ornaments. It is used sparingly (popovers, notices): readings float free of any box.
 */
export function HoloPanel({ title, badge, tone = 'accent', className = '', style, children, ...rest }: HoloPanelProps) {
  const reduce = useReducedMotion()
  return (
    <motion.section
      data-testid={rest['data-testid']}
      data-tone={tone}
      initial={reduce ? false : { opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: 4 }}
      transition={{ duration: 0.22, ease: [0.2, 0.8, 0.2, 1] }}
      style={style}
      className={`rounded-[14px] border ${BORDER[tone]} bg-base-lift shadow-[0_12px_32px_rgba(0,0,0,0.45)] ${className}`}
    >
      {(title || badge) && (
        <header className="flex items-center justify-between gap-2 px-4 pt-3">
          <h3 className="m-0 text-[13px] font-semibold text-ink-soft">{title}</h3>
          <div className="flex items-center gap-2">{badge}</div>
        </header>
      )}
      <div className="px-4 py-3">{children}</div>
    </motion.section>
  )
}
