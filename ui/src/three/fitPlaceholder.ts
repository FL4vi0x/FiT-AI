import * as THREE from 'three'

/**
 * TECHNICAL PLACEHOLDER for the Honda Fit GD (2005). It is NOT a model of that car: it is a procedural body lofted from a
 * hand-set side profile (short bonnet, steep windscreen, tall flat roof, near-vertical tail, four side doors) with
 * approximate Fit proportions (length 3.9 m, width 1.68 m, height 1.54 m, wheelbase 2.45 m). It exists so the scene, the
 * material, the animation and the tests can be built before a licensed, faithful model is available. See
 * docs/poc-08-02-active-hud.md ("Modelo 3D").
 *
 * Units are metres, +X is the front of the car, +Y up, Z across.
 */
export const PLACEHOLDER_ID = 'procedural-placeholder-not-honda-fit-gd'

export const DIM = { length: 3.9, width: 1.68, wheelbase: 2.45, wheelR: 0.29, floor: 0.2 } as const

// top line of the body (x, y), rear to front
const TOP: ReadonlyArray<readonly [number, number]> = [
  [-1.95, 0.5], [-1.94, 0.82], [-1.9, 1.15], [-1.7, 1.46], [-1.5, 1.52], [-0.2, 1.54], [0.0, 1.5], [0.62, 1.0], [1.0, 0.93], [1.45, 0.86], [1.8, 0.72], [1.94, 0.52], [1.94, 0.3],
]

function topAt(x: number): number {
  for (let i = 0; i < TOP.length - 1; i++) {
    const a = TOP[i]!
    const b = TOP[i + 1]!
    if (x >= a[0] && x <= b[0]) {
      const t = (x - a[0]) / (b[0] - a[0] || 1)
      return a[1] + (b[1] - a[1]) * t
    }
  }
  return DIM.floor + 0.1
}

const smooth = (a: number, b: number, v: number) => {
  const t = Math.min(1, Math.max(0, (v - a) / (b - a)))
  return t * t * (3 - 2 * t)
}

/** cross-section at station x: a closed loop of (z, y) points, wider at the belt line, narrower in the greenhouse */
function section(x: number): Array<[number, number]> {
  const yb = DIM.floor
  const yt = Math.max(topAt(x), yb + 0.12)
  const end = 1 - 0.1 * smooth(0.9, 1.95, Math.abs(x)) - 0.16 * smooth(1.55, 1.95, x) - 0.06 * smooth(1.6, 1.95, -x)
  const hs = (DIM.width / 2) * end
  const belt = Math.min(yt, 0.98)
  const half: Array<[number, number]> = [
    [0, yb],
    [hs - 0.12, yb],
    [hs, yb + 0.12],
    [hs, Math.max(yb + 0.14, belt - 0.1)],
    [hs - 0.03, belt],
  ]
  if (yt > belt + 0.04) {
    half.push([hs * 0.8, belt + (yt - belt) * 0.5], [hs * 0.66, yt - 0.04], [hs * 0.5, yt])
  } else {
    half.push([hs * 0.7, yt + 0.01], [hs * 0.35, yt + 0.025])
  }
  half.push([0, yt + 0.03])
  const left = half
    .slice(1, -1)
    .map(([z, y]) => [-z, y] as [number, number])
    .reverse()
  return [...half, ...left]
}

export const STATIONS = 64

/** the lofted body: stations along X, the loop around each one */
export function buildBodyGeometry(): THREE.BufferGeometry {
  const xs = Array.from({ length: STATIONS }, (_, i) => -DIM.length / 2 + 0.01 + (i / (STATIONS - 1)) * (DIM.length - 0.02))
  const loops = xs.map((x) => section(x))
  const n = loops[0]!.length
  const pos: number[] = []
  loops.forEach((loop, i) => loop.forEach(([z, y]) => pos.push(xs[i]!, y, z)))
  const idx: number[] = []
  for (let i = 0; i < STATIONS - 1; i++)
    for (let j = 0; j < n; j++) {
      const a = i * n + j
      const b = i * n + ((j + 1) % n)
      idx.push(a, b, (i + 1) * n + j, b, (i + 1) * n + ((j + 1) % n), (i + 1) * n + j)
    }
  // end caps (fans around a centre point)
  for (const [i, flip] of [[0, true], [STATIONS - 1, false]] as const) {
    const c = pos.length / 3
    const loop = loops[i]!
    const cy = loop.reduce((s, p) => s + p[1], 0) / n
    pos.push(xs[i]!, cy, 0)
    for (let j = 0; j < n; j++) {
      const a = i * n + j
      const b = i * n + ((j + 1) % n)
      flip ? idx.push(c, b, a) : idx.push(c, a, b)
    }
  }
  const g = new THREE.BufferGeometry()
  g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3))
  g.setIndex(idx)
  g.computeVertexNormals()
  return g
}

const seg = (pts: Array<[number, number, number]>) => {
  const g = new THREE.BufferGeometry().setFromPoints(pts.map((p) => new THREE.Vector3(...p)))
  return g
}

/** technical lines: station rings, belt line, door cuts, wheel arches, headlamps, grille, mirrors */
export function buildDetailLines(): THREE.BufferGeometry[] {
  const out: THREE.BufferGeometry[] = []
  const hw = DIM.width / 2
  // belt line + window line, both sides
  for (const s of [1, -1]) {
    out.push(seg([[-1.85, 0.98, s * (hw - 0.03)], [-0.2, 1.0, s * (hw - 0.03)], [0.7, 0.98, s * (hw - 0.03)], [1.3, 0.9, s * (hw - 0.05)]]))
    out.push(seg([[-1.62, 1.38, s * hw * 0.64], [-0.15, 1.42, s * hw * 0.62], [0.52, 1.02, s * hw * 0.78]]))
    // door cuts: front door, rear door and tailgate edge
    for (const x of [0.72, 0.0, -0.9, -1.55]) out.push(seg([[x, 0.3, s * (hw - 0.005)], [x, 0.98, s * (hw - 0.005)], [x - 0.04, 1.4, s * hw * 0.64]]))
    // door handles
    out.push(seg([[0.1, 0.86, s * (hw + 0.005)], [0.28, 0.86, s * (hw + 0.005)]]))
    out.push(seg([[-0.78, 0.86, s * (hw + 0.005)], [-0.6, 0.86, s * (hw + 0.005)]]))
    // headlamp (a swept wedge on the nose) and tail lamp
    out.push(seg([[1.84, 0.74, s * 0.42], [1.93, 0.62, s * 0.62], [1.86, 0.56, s * 0.74], [1.7, 0.7, s * 0.78], [1.84, 0.74, s * 0.42]]))
    out.push(seg([[-1.93, 0.78, s * 0.62], [-1.92, 0.56, s * 0.7], [-1.9, 0.9, s * 0.78], [-1.93, 0.78, s * 0.62]]))
    // wing mirror
    out.push(seg([[0.55, 0.98, s * (hw - 0.02)], [0.5, 1.04, s * (hw + 0.14)], [0.6, 1.1, s * (hw + 0.12)], [0.62, 0.99, s * (hw - 0.02)]]))
  }
  // grille and bumper intake
  for (const y of [0.5, 0.56, 0.62]) out.push(seg([[1.945, y, -0.4], [1.945, y, 0.4]]))
  out.push(seg([[1.94, 0.34, -0.55], [1.94, 0.34, 0.55]]))
  // bonnet crease and windscreen base
  out.push(seg([[0.65, 1.0, -0.5], [1.4, 0.88, -0.5]]))
  out.push(seg([[0.65, 1.0, 0.5], [1.4, 0.88, 0.5]]))
  out.push(seg([[0.62, 1.0, -0.62], [0.62, 1.0, 0.62]]))
  out.push(...buildFeatureLines())
  return out
}

export interface WheelParts {
  tyre: THREE.BufferGeometry
  rim: THREE.BufferGeometry
  spokes: THREE.BufferGeometry
  positions: Array<[number, number, number]>
}

export function buildWheel(): WheelParts {
  const tyre = new THREE.TorusGeometry(DIM.wheelR - 0.06, 0.085, 10, 28)
  const rim = new THREE.RingGeometry(0.12, 0.2, 28, 1)
  const pts: THREE.Vector3[] = []
  for (let k = 0; k < 5; k++) {
    const a = (k / 5) * Math.PI * 2
    pts.push(new THREE.Vector3(Math.cos(a) * 0.04, Math.sin(a) * 0.04, 0.0), new THREE.Vector3(Math.cos(a) * 0.2, Math.sin(a) * 0.2, 0))
  }
  const spokes = new THREE.BufferGeometry().setFromPoints(pts)
  const f = DIM.wheelbase / 2
  const z = DIM.width / 2 - 0.1
  return {
    tyre,
    rim,
    spokes,
    positions: [[f, DIM.wheelR, z], [f, DIM.wheelR, -z], [-f, DIM.wheelR, z], [-f, DIM.wheelR, -z]],
  }
}

/**
 * Controlled technical wireframe of the body: longitudinal lines along selected loop points (sill, shoulder, belt, roof edge,
 * centre) and cross-section rings every few stations. Far lighter than drawing every polygon edge.
 */
export function buildBodyLines(): THREE.BufferGeometry {
  const xs = Array.from({ length: STATIONS }, (_, i) => -DIM.length / 2 + 0.01 + (i / (STATIONS - 1)) * (DIM.length - 0.02))
  const loops = xs.map((x) => section(x))
  const n = loops[0]!.length
  const pts: number[] = []
  const push = (x: number, y: number, z: number) => pts.push(x, y, z)
  // longitudinal: every loop point of the right side plus its mirror (indices are symmetric)
  for (let j = 1; j < n; j += 2) {
    for (let i = 0; i < STATIONS - 1; i++) {
      const [z0, y0] = loops[i]![j]!
      const [z1, y1] = loops[i + 1]![j]!
      push(xs[i]!, y0, z0)
      push(xs[i + 1]!, y1, z1)
    }
  }
  // cross-section rings
  for (let i = 5; i < STATIONS - 1; i += 11) {
    const loop = loops[i]!
    for (let j = 0; j < n; j++) {
      const [z0, y0] = loop[j]!
      const [z1, y1] = loop[(j + 1) % n]!
      push(xs[i]!, y0, z0)
      push(xs[i]!, y1, z1)
    }
  }
  const g = new THREE.BufferGeometry()
  g.setAttribute('position', new THREE.Float32BufferAttribute(pts, 3))
  return g
}

const lerp = (a: number, b: number, t: number) => a + (b - a) * t
const loop = (pts: Array<[number, number, number]>) => [...pts, pts[0]!]

/** a point on the greenhouse side surface at station x: f = 0 at the belt line, 1 at the roof edge */
function glassPoint(x: number, f: number, side: number): [number, number, number] {
  const yt = Math.max(topAt(x), DIM.floor + 0.12)
  const belt = Math.min(yt, 0.98)
  const hs = (DIM.width / 2) * (1 - 0.1 * smooth(0.9, 1.95, Math.abs(x)) - 0.06 * smooth(1.6, 1.95, -x))
  return [x, lerp(belt + 0.03, yt - 0.04, f), side * lerp(hs - 0.03, hs * 0.66, f) * 1.003]
}

const glassPoly = (x0: number, x1: number, side: number): Array<[number, number, number]> => {
  const pts: Array<[number, number, number]> = []
  for (let k = 0; k <= 4; k++) pts.push(glassPoint(lerp(x0, x1, k / 4), 0.1, side))
  for (let k = 4; k >= 0; k--) pts.push(glassPoint(lerp(x0, x1, k / 4), 0.92, side))
  return loop(pts)
}

/** identity details: glass, windscreen, grille with the H, intake, fog lamps, wheel arches */
export function buildFeatureLines(): THREE.BufferGeometry[] {
  const out: THREE.BufferGeometry[] = []
  const hw = DIM.width / 2
  for (const s of [1, -1]) {
    out.push(seg(glassPoly(0.06, 0.6, s)))
    out.push(seg(glassPoly(-0.84, -0.08, s)))
    out.push(seg(glassPoly(-1.5, -0.95, s)))
    // wheel arches (half circles on the flank)
    for (const wx of [DIM.wheelbase / 2, -DIM.wheelbase / 2]) {
      const arc: Array<[number, number, number]> = []
      for (let k = 0; k <= 16; k++) {
        const a = (k / 16) * Math.PI
        arc.push([wx + Math.cos(a) * 0.37, DIM.wheelR + Math.sin(a) * 0.37, s * (hw - 0.02)])
      }
      out.push(seg(arc))
    }
    // fog lamp
    const fog: Array<[number, number, number]> = []
    for (let k = 0; k <= 12; k++) fog.push([1.945, 0.36 + Math.sin((k / 12) * Math.PI * 2) * 0.045, s * (0.52 + Math.cos((k / 12) * Math.PI * 2) * 0.05)])
    out.push(seg(fog))
  }
  // windscreen and rear window
  out.push(seg(loop([[0.58, 1.02, -0.6], [0.04, 1.48, -0.42], [0.04, 1.48, 0.42], [0.58, 1.02, 0.6]])))
  out.push(seg(loop([[-1.88, 1.1, -0.58], [-1.62, 1.44, -0.42], [-1.62, 1.44, 0.42], [-1.88, 1.1, 0.58]])))
  // grille frame with the H, and the lower intake
  out.push(seg(loop([[1.948, 0.5, -0.34], [1.948, 0.64, -0.3], [1.948, 0.64, 0.3], [1.948, 0.5, 0.34]])))
  out.push(seg([[1.95, 0.52, -0.1], [1.95, 0.62, -0.1]]))
  out.push(seg([[1.95, 0.52, 0.1], [1.95, 0.62, 0.1]]))
  out.push(seg([[1.95, 0.57, -0.1], [1.95, 0.57, 0.1]]))
  out.push(seg(loop([[1.94, 0.3, -0.56], [1.94, 0.44, -0.4], [1.94, 0.44, 0.4], [1.94, 0.3, 0.56]])))
  // number plate recess and rear lamp bars
  out.push(seg(loop([[-1.945, 0.46, -0.26], [-1.945, 0.46, 0.26], [-1.945, 0.6, 0.26], [-1.945, 0.6, -0.26]])))
  return out
}
