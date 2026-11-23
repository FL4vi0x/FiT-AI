import { motion } from 'motion/react'
import { EMBLEM } from './geometry'
import { HONDA_EMBLEM_BOX, HONDA_FRAME_D, HONDA_H_D } from './hondaEmblemPaths'
import { emblemVariants, rimGlowVariants } from '../../motion/variants'

const S = EMBLEM.width / HONDA_EMBLEM_BOX.w
const PLACE = `translate(${EMBLEM.centerX - EMBLEM.width / 2} ${EMBLEM.centerY - (HONDA_EMBLEM_BOX.h * S) / 2}) scale(${S})`

/**
 * The classic Honda emblem as chrome: the two vector paths (frame and H) painted with banded metal gradients (bright sky, a dark
 * horizon band, a lighter lower reflection), an inner highlight and a thin amber light on the outer edge. The amber is light on
 * the metal, not a fill: the symbol is never deformed. Geometry: Wikimedia Commons "File:Honda.svg" (see hondaEmblemPaths.ts).
 * HONDA is a trademark of Honda Motor Co., Ltd.
 */
export function HondaEmblem() {
  return (
    <motion.g variants={emblemVariants} style={{ transformBox: 'fill-box', transformOrigin: 'center' }}>
      <defs>
        <linearGradient id="cr-frame" gradientUnits="userSpaceOnUse" x1="0" y1="0" x2="0" y2="1789">
          <stop offset="0" stopColor="#F7F7F7" />
          <stop offset="0.2" stopColor="#D9D9DB" />
          <stop offset="0.46" stopColor="#8E8E93" />
          <stop offset="0.5" stopColor="#2B2B2E" />
          <stop offset="0.56" stopColor="#7C7A79" />
          <stop offset="0.8" stopColor="#CFC6BD" />
          <stop offset="1" stopColor="#B07A45" />
        </linearGradient>
        <linearGradient id="cr-h" gradientUnits="userSpaceOnUse" x1="0" y1="151" x2="0" y2="1657">
          <stop offset="0" stopColor="#FBFBFB" />
          <stop offset="0.3" stopColor="#E3E3E4" />
          <stop offset="0.52" stopColor="#9A9A9F" />
          <stop offset="0.58" stopColor="#3A3A3D" />
          <stop offset="0.7" stopColor="#A9A8A8" />
          <stop offset="0.88" stopColor="#D9D6D3" />
          <stop offset="1" stopColor="#6C6967" />
        </linearGradient>
        <linearGradient id="cr-side" gradientUnits="userSpaceOnUse" x1="441" y1="0" x2="1759" y2="0">
          <stop offset="0" stopColor="#fff" stopOpacity="0.35" />
          <stop offset="0.25" stopColor="#fff" stopOpacity="0" />
          <stop offset="0.75" stopColor="#000" stopOpacity="0" />
          <stop offset="1" stopColor="#000" stopOpacity="0.35" />
        </linearGradient>
        <clipPath id="cr-clip-frame">
          <path d={HONDA_FRAME_D} />
        </clipPath>
        <clipPath id="cr-clip-h">
          <path d={HONDA_H_D} />
        </clipPath>
      </defs>
      <g transform={PLACE}>
        {/* soft amber light around the outline (a wide, very faint stroke under the metal; its opacity comes in with the rim) */}
        <g opacity={0.16}>
          <motion.path variants={rimGlowVariants} d={HONDA_FRAME_D} fill="none" stroke="#FF8500" strokeWidth={150} strokeLinejoin="round" />
        </g>
        <g opacity={0.5}>
          <motion.path variants={rimGlowVariants} d={HONDA_FRAME_D} fill="none" stroke="#FF9A1F" strokeWidth={56} strokeLinejoin="round" />
        </g>
        {/* the thin amber edge: half of this stroke is hidden by the fill drawn on top */}
        <path d={HONDA_FRAME_D} fill="none" stroke="#FFB44A" strokeWidth={26} strokeLinejoin="round" />
        <path d={HONDA_FRAME_D} fill="url(#cr-frame)" />
        <path d={HONDA_FRAME_D} fill="url(#cr-side)" />
        {/* inner bevel: a light line just inside the edge, clipped to the shape */}
        <g clipPath="url(#cr-clip-frame)">
          <path d={HONDA_FRAME_D} fill="none" stroke="#fff" strokeWidth={34} opacity={0.5} />
          <path d={HONDA_FRAME_D} fill="none" stroke="#000" strokeWidth={14} opacity={0.35} transform="translate(8 14)" />
        </g>
        <path d={HONDA_H_D} fill="none" stroke="#FFB44A" strokeWidth={14} opacity={0.5} strokeLinejoin="round" />
        <path d={HONDA_H_D} fill="url(#cr-h)" />
        <path d={HONDA_H_D} fill="url(#cr-side)" />
        <g clipPath="url(#cr-clip-h)">
          <path d={HONDA_H_D} fill="none" stroke="#fff" strokeWidth={30} opacity={0.55} />
        </g>
      </g>
    </motion.g>
  )
}
