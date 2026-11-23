// Geometry of the Standby screen: one coordinate system, the pixel space of the approved reference image (1672 x 941), so every
// number here can be checked against the picture. Values come from measurements of that image (centres, widths, angles,
// colours), not from guesses. The stage scales the whole thing to the window.
//
// Nothing in this file is an official Honda asset. The emblem is a local vector reconstruction, from the measured geometry of
// the reference, and is a TEMPORARY placeholder (see docs/poc-08-01-standby-screen.md, "Marca e licenciamento").

export const VIEW = { w: 1672, h: 941 } as const

export interface Pt {
  x: number
  y: number
}

/** Catmull-Rom through the points, as one cubic Bezier path (so an arc given by a few measured points is smooth). */
export function smoothPath(points: ReadonlyArray<readonly [number, number]>): string {
  if (points.length < 2) return ''
  const p = (i: number) => points[Math.min(points.length - 1, Math.max(0, i))] as readonly [number, number]
  let d = `M ${p(0)[0]} ${p(0)[1]}`
  for (let i = 0; i < points.length - 1; i++) {
    const p0 = p(i - 1)
    const p1 = p(i)
    const p2 = p(i + 1)
    const p3 = p(i + 2)
    const c1: [number, number] = [p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6]
    const c2: [number, number] = [p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6]
    d += ` C ${c1[0].toFixed(1)} ${c1[1].toFixed(1)} ${c2[0].toFixed(1)} ${c2[1].toFixed(1)} ${p2[0]} ${p2[1]}`
  }
  return d
}

export function roundedRect(x: number, y: number, w: number, h: number, r: number): string {
  return `M ${x + r} ${y} H ${x + w - r} A ${r} ${r} 0 0 1 ${x + w} ${y + r} V ${y + h - r} A ${r} ${r} 0 0 1 ${x + w - r} ${y + h} H ${x + r} A ${r} ${r} 0 0 1 ${x} ${y + h - r} V ${y + r} A ${r} ${r} 0 0 1 ${x + r} ${y} Z`
}

// ───────────────────────── emblem ─────────────────────────
export const AXIS_X = 833.75 // the emblem and the wordmark are centred here (measured), not at 836

/**
 * Where the classic Honda emblem sits in the stage: centred on AXIS_X and on the measured vertical centre of the reference
 * emblem (y 309..481), with the native proportion of the vector (2200.6 x 1789.2) preserved: width 218, height ~177.
 */
export const EMBLEM = { width: 218, centerX: AXIS_X, centerY: 395.5 } as const

// ───────────────────────── wordmark ─────────────────────────
/**
 * "FIT AI": a wide italic sans built as paths so it renders the same everywhere (no font to load) and so FIT and AI can be
 * painted independently. Measured: cap height 50, baseline y 556.5, slant 23.3 degrees, vertical strokes ~16 px, bars ~9 px,
 * FIT x 664..866, AI x 876..1007. The glyphs are drawn upright, in absolute baseline x coordinates, with the origin of the
 * skew on the baseline: the transform below leans them (top to the right) without moving the baseline.
 */
export const WORDMARK = {
  baselineY: 556.5,
  capHeight: 50,
  slantDeg: 23.3,
  /** transform that leans the upright glyphs (their y is 0 at the baseline, negative above it) */
  transform: 'translate(0 556.5) skewX(-23.3)',
  bar: 8.5,
  stem: 16,
  fit: {
    // F: stem, top arm (with a swept corner) and a shorter middle arm
    F: 'M 664 0 V -42 Q 664 -50 676 -50 H 731.5 V -41.5 H 680 V -28.5 H 722 V -20.5 H 680 V 0 Z',
    I1: 'M 748 0 V -50 H 764 V 0 Z',
    T: 'M 768.5 -50 H 844.5 V -41.5 H 814.5 V 0 H 798.5 V -41.5 H 768.5 Z',
  },
  ai: {
    // A: wide, flat apex, counter triangle above a crossbar
    A: 'M 876 0 L 908 -50 H 930 L 962 0 H 944 L 938.5 -10 H 899.5 L 894 0 Z M 904.8 -18.5 H 933.2 L 919 -40.6 Z',
    I2: 'M 971 0 V -50 H 987 V 0 Z',
  },
  /** vertical gradients in the (skewed) glyph space, y from the cap line (-50) to the baseline (0), from the sampled colours */
  fitStops: [
    [0, '#FBFBFB'],
    [0.12, '#FAFAFA'],
    [0.34, '#DDDDDC'],
    [0.55, '#9B9897'],
    [0.68, '#7A7674'],
    [0.84, '#817771'],
    [1, '#AA9381'],
  ],
  aiStops: [
    [0, '#FFD27A'],
    [0.1, '#FFCA68'],
    [0.22, '#FEB741'],
    [0.34, '#FD9E11'],
    [0.46, '#FE8C02'],
    [0.58, '#FD7C01'],
    [0.7, '#FE7104'],
    [0.82, '#FB6901'],
    [1, '#F86E03'],
  ],
} as const

// ───────────────────────── arcs ─────────────────────────
export const ARC_MIRROR_X = 1669 // left + right = 1669 (measured), i.e. mirror about x = 834.5

/** ridge points of the LEFT arcs, from the floor up to beyond the top of the frame (measured; the last ones are extrapolated) */
export const ARC_INNER_LEFT: ReadonlyArray<readonly [number, number]> = [
  [249, 664], [244, 640], [236, 600], [231, 560], [228, 520], [229, 480], [232, 440], [239, 400], [248, 360], [261, 320],
  [276, 280], [295, 240], [317, 200], [345, 160], [377, 120], [416, 80], [466, 30], [512, -20],
]
export const ARC_OUTER_LEFT: ReadonlyArray<readonly [number, number]> = [
  [106, 664], [99, 620], [94, 570], [92, 520], [93, 480], [96, 440], [102, 400], [110, 360], [120, 320], [132, 280],
  [147, 240], [164, 200], [185, 160], [209, 120], [238, 80], [271, 40], [310, 2], [352, -40],
]

/** brightness of the ridge along its height (stop colours sampled from the image), as [y, colour] from the floor upwards */
export const ARC_INNER_STOPS: ReadonlyArray<readonly [number, string]> = [
  [664, '#2E1000'], [640, '#4F1800'], [600, '#5B1F00'], [560, '#4B1700'], [520, '#401200'], [480, '#421000'], [440, '#612101'],
  [400, '#802D01'], [360, '#BC4900'], [320, '#F16501'], [280, '#FFB517'], [240, '#FFFDBB'], [200, '#F9C95D'], [160, '#DC5A01'],
  [120, '#511F01'], [80, '#130701'], [30, '#000000'],
]
export const ARC_OUTER_STOPS: ReadonlyArray<readonly [number, string]> = [
  [664, '#000000'], [520, '#030100'], [480, '#070100'], [440, '#0D0400'], [400, '#130500'], [360, '#220900'], [320, '#3F1301'],
  [280, '#5A1F00'], [240, '#A63F01'], [200, '#9B3B00'], [160, '#913001'], [120, '#401400'], [80, '#200A00'], [40, '#0E0400'], [0, '#000000'],
]

// ───────────────────────── light ─────────────────────────
export const HORIZON = { x: 835, y: 664, coreHalfWidth: 92, glowHalfWidth: 190, poolDepth: 175 } as const

export const SIDE_LINES = {
  y: 534.4,
  thickness: 1.4,
  left: { x0: 431, x1: 611, peakX: 585 },
  right: { x0: 1057, x1: 1240, peakX: 1085 },
} as const

export const FLOOR = {
  y: 664,
  /** the reflection of the wordmark is a vertical mirror about the floor line */
  mirrorY: 664,
  streakLeftX: 246.5,
  streakRightX: 1422,
  streakY0: 640,
  streakY1: 800,
  streakPeakY: 720,
  streakWidth: 10,
} as const
