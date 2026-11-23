// Geometry of the stage. Everything is expressed in ONE logical coordinate system (STAGE, 1200 x 640) that the StageFrame
// scales to the window, so the SVG layers and the HTML readouts stay aligned at any size.
//
// The car is drawn in its own 1000 x 440 box (side view, front to the right, ground at y = 392) and placed on the stage
// with CAR. Zone anchors are given in CAR coordinates and converted with carToStage(). The readouts are placed from the
// anchors, close to their region and outside the body, so a leader never has to cross the car.

export interface Pt {
  x: number
  y: number
}
export interface Rect {
  x: number
  y: number
  w: number
  h: number
}

export const STAGE = { w: 1200, h: 640 } as const
export const CAR = { x: 150, y: 176, scale: 0.86 } as const

export function carToStage(p: Pt): Pt {
  return { x: CAR.x + p.x * CAR.scale, y: CAR.y + p.y * CAR.scale }
}

export type ZoneId = 'powertrain' | 'cooling' | 'motion' | 'cabin'

export interface ZoneDef {
  id: ZoneId
  /** Shown only on hover/focus (title), never painted on the car. */
  label: string
  /** Where the leader lands, in CAR coordinates. */
  anchor: Pt
  /** Highlight shapes, in CAR coordinates. */
  shapes: ({ kind: 'rect'; x: number; y: number; w: number; h: number; r: number } | { kind: 'circle'; cx: number; cy: number; r: number })[]
}

export const WHEEL_REAR: Pt = { x: 190, y: 322 }
export const WHEEL_FRONT: Pt = { x: 778, y: 322 }

export const ZONES: Record<ZoneId, ZoneDef> = {
  powertrain: {
    id: 'powertrain',
    label: 'Powertrain',
    anchor: { x: 868, y: 238 },
    shapes: [{ kind: 'rect', x: 806, y: 204, w: 118, h: 72, r: 14 }],
  },
  cooling: {
    id: 'cooling',
    label: 'Radiador',
    anchor: { x: 940, y: 270 },
    shapes: [{ kind: 'rect', x: 924, y: 232, w: 32, h: 76, r: 10 }],
  },
  motion: {
    id: 'motion',
    label: 'Rodas',
    anchor: { x: WHEEL_FRONT.x, y: 392 }, // the contact patch of the front tyre
    shapes: [
      { kind: 'circle', cx: WHEEL_REAR.x, cy: WHEEL_REAR.y, r: 76 },
      { kind: 'circle', cx: WHEEL_FRONT.x, cy: WHEEL_FRONT.y, r: 76 },
    ],
  },
  cabin: {
    id: 'cabin',
    label: 'ECU · OBD',
    anchor: { x: 688, y: 150 },
    shapes: [{ kind: 'rect', x: 628, y: 112, w: 112, h: 72, r: 12 }],
  },
}

export function zoneAnchor(id: ZoneId): Pt {
  return carToStage(ZONES[id].anchor)
}

export type PanelId = 'system' | 'rpm' | 'speed' | 'temp'

export interface PanelLayout {
  id: PanelId
  zone: ZoneId
  /** Box of the HTML readout, in STAGE coordinates. */
  rect: Rect
  /** Where the leader leaves the readout, in STAGE coordinates. */
  from: Pt
  /** Which edge of the box the text hugs (the side facing the leader). */
  align: 'left' | 'right'
}

const engine = zoneAnchor('powertrain')
const radiator = zoneAnchor('cooling')
const tyre = zoneAnchor('motion')
const cabin = zoneAnchor('cabin')

export const PANELS: Record<PanelId, PanelLayout> = {
  // above the bonnet, clear of the windscreen
  rpm: { id: 'rpm', zone: 'powertrain', rect: { x: engine.x - 30, y: engine.y - 206, w: 190, h: 112 }, from: { x: engine.x - 16, y: engine.y - 90 }, align: 'left' },
  // in front of the nose, level with the radiator
  temp: { id: 'temp', zone: 'cooling', rect: { x: radiator.x + 52, y: radiator.y - 58, w: 170, h: 112 }, from: { x: radiator.x + 44, y: radiator.y }, align: 'left' },
  // under the front wheel
  speed: { id: 'speed', zone: 'motion', rect: { x: tyre.x - 84, y: tyre.y + 22, w: 170, h: 92 }, from: { x: tyre.x, y: tyre.y + 18 }, align: 'left' },
  // above the roof: only when there is something about the link to say
  system: { id: 'system', zone: 'cabin', rect: { x: cabin.x - 300, y: 52, w: 260, h: 104 }, from: { x: cabin.x - 40, y: 118 }, align: 'right' },
}

/** The AI core: a quiet light on the dashboard, where the head unit lives. */
export const CORE_POS: Pt = carToStage({ x: 706, y: 172 })
export const CORE_SIZE = 44

/**
 * Hairline leader: run straight out of the readout, then a single 45 degree turn into the anchor (or a straight line when
 * the anchor is level with, or directly under, the start).
 */
export function leaderPoints(from: Pt, to: Pt): Pt[] {
  const dx = to.x - from.x
  const dy = to.y - from.y
  const adx = Math.abs(dx)
  const ady = Math.abs(dy)
  if (adx < 1 || ady < 1) return [from, to]
  if (adx >= ady) return [from, { x: to.x - Math.sign(dx) * ady, y: from.y }, to]
  return [from, { x: from.x, y: to.y - Math.sign(dy) * adx }, to]
}

export function panelLeader(id: PanelId): Pt[] {
  const p = PANELS[id]
  return leaderPoints(p.from, zoneAnchor(p.zone))
}

export function toPath(points: Pt[]): string {
  return points.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(' ')
}

/** Faint links from the core to a module while it thinks. */
export function busPoints(target: Pt): Pt[] {
  return [CORE_POS, target]
}

/** Points that come alive during a scan, in CAR coordinates (the zone anchors and the dashboard light). */
export const SCAN_NODES: Pt[] = [ZONES.powertrain.anchor, ZONES.cooling.anchor, ZONES.motion.anchor, ZONES.cabin.anchor, { x: 706, y: 172 }]
