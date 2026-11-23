import type { ReactNode } from 'react'
import { VIEW } from './geometry'
import styles from '../../screens/StandbyScreen/StandbyScreen.module.css'

/** One full-stage SVG layer in the reference pixel space. Decorative unless told otherwise. */
export function Layer({ children, className = '', decorative = true, testId }: { children: ReactNode; className?: string; decorative?: boolean; testId?: string }) {
  return (
    <svg
      className={`${styles.layer} ${className}`}
      viewBox={`0 0 ${VIEW.w} ${VIEW.h}`}
      preserveAspectRatio="xMidYMid meet"
      aria-hidden={decorative ? true : undefined}
      focusable="false"
      data-testid={testId}
    >
      {children}
    </svg>
  )
}

/** Gradient stops from [offset, colour] pairs. */
export function Stops({ list }: { list: ReadonlyArray<readonly [number, string]> }) {
  return (
    <>
      {list.map(([o, c]) => (
        <stop key={`${o}-${c}`} offset={o} stopColor={c} />
      ))}
    </>
  )
}
