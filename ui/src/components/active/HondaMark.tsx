import { HONDA_EMBLEM_BOX, HONDA_FRAME_D, HONDA_H_D } from '../standby/hondaEmblemPaths'

/** Small flat chrome version of the emblem for the header (same geometry as the Standby emblem; see hondaEmblemPaths.ts). */
export function HondaMark({ height = 38 }: { height?: number }) {
  const w = (height * (HONDA_EMBLEM_BOX.w + 120)) / (HONDA_EMBLEM_BOX.h + 120)
  return (
    <svg width={w} height={height} viewBox={`-60 -60 ${HONDA_EMBLEM_BOX.w + 120} ${HONDA_EMBLEM_BOX.h + 120}`} aria-hidden="true" focusable="false">
      <defs>
        <linearGradient id="hm-metal" gradientUnits="userSpaceOnUse" x1="0" y1="0" x2="0" y2="1789">
          <stop offset="0" stopColor="#F7F7F7" />
          <stop offset="0.5" stopColor="#8E8E93" />
          <stop offset="0.54" stopColor="#2B2B2E" />
          <stop offset="1" stopColor="#D5CCC3" />
        </linearGradient>
      </defs>
      <path d={HONDA_FRAME_D} fill="none" stroke="#FF9A1F" strokeWidth="46" strokeLinejoin="round" />
      <path d={HONDA_FRAME_D} fill="url(#hm-metal)" />
      <path d={HONDA_H_D} fill="url(#hm-metal)" />
    </svg>
  )
}
