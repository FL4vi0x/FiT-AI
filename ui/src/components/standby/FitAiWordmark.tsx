import { motion } from 'motion/react'
import { WORDMARK } from './geometry'
import { Stops } from './Layer'
import { sweepVariants, wordmarkVariants } from '../../motion/variants'

/** The letters themselves (no animation), reused by the wordmark and by its reflection. */
export function WordmarkGlyphs({ id }: { id: string }) {
  return (
    <>
      <defs>
        <linearGradient id={`${id}-fit`} gradientUnits="userSpaceOnUse" x1="0" y1="-50" x2="0" y2="0">
          <Stops list={WORDMARK.fitStops} />
        </linearGradient>
        <linearGradient id={`${id}-ai`} gradientUnits="userSpaceOnUse" x1="0" y1="-50" x2="0" y2="0">
          <Stops list={WORDMARK.aiStops} />
        </linearGradient>
      </defs>
      <g transform={WORDMARK.transform}>
        <g fill={`url(#${id}-fit)`}>
          <path d={WORDMARK.fit.F} />
          <path d={WORDMARK.fit.I1} />
          <path d={WORDMARK.fit.T} />
        </g>
        <g fill={`url(#${id}-ai)`}>
          <path d={WORDMARK.ai.A} fillRule="evenodd" />
          <path d={WORDMARK.ai.I2} />
        </g>
      </g>
    </>
  )
}

/** FIT (silver) + AI (orange), fading in once with a single glint travelling across the letters. */
export function FitAiWordmark() {
  return (
    <motion.g variants={wordmarkVariants}>
      <WordmarkGlyphs id="wm" />
      <defs>
        <clipPath id="wm-clip">
          <g transform={WORDMARK.transform}>
            <path d={WORDMARK.fit.F} />
            <path d={WORDMARK.fit.I1} />
            <path d={WORDMARK.fit.T} />
            <path d={WORDMARK.ai.A} fillRule="evenodd" />
            <path d={WORDMARK.ai.I2} />
          </g>
        </clipPath>
        <linearGradient id="wm-glint" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0" stopColor="#ffffff" stopOpacity="0" />
          <stop offset="0.5" stopColor="#ffffff" stopOpacity="0.85" />
          <stop offset="1" stopColor="#ffffff" stopOpacity="0" />
        </linearGradient>
      </defs>
      <g clipPath="url(#wm-clip)">
        <g transform={WORDMARK.transform}>
          <motion.rect variants={sweepVariants} x={620} y={-52} width={44} height={54} fill="url(#wm-glint)" />
        </g>
      </g>
    </motion.g>
  )
}
