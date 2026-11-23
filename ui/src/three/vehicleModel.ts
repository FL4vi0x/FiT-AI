import * as THREE from 'three'
import { getAsset, roleOf, type Appearance, type FrontAxis, type PartRole, type VehicleAsset, type VehicleAssetId } from './vehicleAssets'
import { makeHoloMaterial, makeLineMaterial, BODY_SHADOW, type HoloLook, type HoloUniforms } from './hologram'
import type { ExteriorMasks } from './visibility'

/** the official length of the Honda Fit LX 2005 (manual: 3830 mm). The model is scaled UNIFORMLY to it: no axis is ever stretched. */
export const TARGET_LENGTH = 3.83

export interface ModelStats {
  meshes: number
  triangles: number
  /** size after normalisation, metres */
  lengthM: number
  widthM: number
  heightM: number
  loadMs: number
  materials: number
}

export interface LoadedVehicle {
  /** normalised car: nose toward +X, wheels on y = 0, centred on x = z = 0. The ORIGINAL materials are still on its meshes. */
  root: THREE.Group
  stats: ModelStats
  /** the glTF `asset` block of the file (generator, copyright, extras with author/licence when the exporter wrote them), kept untouched */
  gltfAsset: Record<string, unknown>
  dispose(): void
}

// rotation about +Y that brings the file's nose axis onto +X
const FRONT_ROTATION: Record<FrontAxis, number> = { '+x': 0, '-x': Math.PI, '+z': Math.PI / 2, '-z': -Math.PI / 2 }

/**
 * Orient, scale and centre a freshly loaded scene. Orientation: the nose goes to +X (where the rest of the scene expects it).
 * Scale: ONE factor, so the length becomes 3.83 m and the proportions of the model are untouched. Position: centred on the
 * plan, resting on the floor.
 */
export function normalizeModel(scene: THREE.Object3D, front: FrontAxis): THREE.Group {
  const holder = new THREE.Group()
  holder.add(scene)
  holder.rotation.y = FRONT_ROTATION[front]
  holder.updateMatrixWorld(true)
  const box = new THREE.Box3().setFromObject(holder, true)
  const size = box.getSize(new THREE.Vector3())
  if (!(size.x > 0)) throw new Error('empty or degenerate model')
  const s = TARGET_LENGTH / size.x
  const c = box.getCenter(new THREE.Vector3())
  holder.scale.setScalar(s)
  holder.position.set(-c.x * s, -box.min.y * s, -c.z * s)
  const outer = new THREE.Group()
  outer.add(holder)
  outer.updateMatrixWorld(true)
  return outer
}

function meshesOf(root: THREE.Object3D): THREE.Mesh[] {
  const out: THREE.Mesh[] = []
  root.traverse((o) => {
    if ((o as THREE.Mesh).isMesh) out.push(o as THREE.Mesh)
  })
  return out
}

export function disposeObject(root: THREE.Object3D) {
  for (const m of meshesOf(root)) {
    m.geometry.dispose()
    for (const mat of Array.isArray(m.material) ? m.material : [m.material]) {
      for (const v of Object.values(mat)) if (v && (v as THREE.Texture).isTexture) (v as THREE.Texture).dispose()
      mat.dispose()
    }
  }
}

export function describeModel(root: THREE.Object3D, loadMs: number): ModelStats {
  const ms = meshesOf(root)
  let triangles = 0
  const mats = new Set<THREE.Material>()
  for (const m of ms) {
    const g = m.geometry
    triangles += (g.index ? g.index.count : (g.getAttribute('position')?.count ?? 0)) / 3
    for (const mat of Array.isArray(m.material) ? m.material : [m.material]) mats.add(mat)
  }
  const size = new THREE.Box3().setFromObject(root, true).getSize(new THREE.Vector3())
  return { meshes: ms.length, triangles: Math.round(triangles), lengthM: size.x, widthM: size.z, heightM: size.y, loadMs, materials: mats.size }
}

/** Load a GLB from `url` (a local dev-server URL for the preview assets) and normalise it. Rejects on any failure. */
export async function loadVehicleGlb(url: string, id: VehicleAssetId = 'placeholder'): Promise<LoadedVehicle> {
  const { GLTFLoader } = await import('three/examples/jsm/loaders/GLTFLoader.js')
  const t0 = performance.now()
  const gltf = await new GLTFLoader().loadAsync(url)
  const asset = getAsset(id)
  let root: THREE.Group
  try {
    root = normalizeModel(gltf.scene, asset.frontAxis)
  } catch (e) {
    disposeObject(gltf.scene)
    throw e
  }
  return {
    root,
    stats: describeModel(root, performance.now() - t0),
    gltfAsset: (gltf.asset ?? {}) as Record<string, unknown>,
    dispose: () => disposeObject(root),
  }
}

// ───────────────────────── appearances ─────────────────────────
export interface PartLook extends HoloLook {
  /** amber edge-line opacity */
  line: number
  /** crease angle (degrees) above which an edge is drawn: only the real panel lines, never every triangle */
  angle: number
  hot: boolean
  grey: string
}

/**
 * The visual hierarchy of the hologram. The body panels carry the shape (strongest rim light, the most lines); lamps and small
 * details stand out against it; glass and tyres are quieter; and whatever is only INTERIOR (see INTERIOR_LOOK) is a ghost.
 */
export const PART_LOOKS: Record<PartRole, PartLook> = {
  // a sharp rim (power 2.8) lights the silhouette strongly and leaves flat surfaces dark: the lines carry the panels
  body: { base: BODY_SHADOW, rim: 2.2, alpha: 0.3, fresAlpha: 0.75, fresPower: 2.8, line: 0.8, angle: 26, hot: true, grey: '#a9a9ad' },
  trim: { base: '#0b0603', rim: 0.8, alpha: 0.5, fresAlpha: 0.4, fresPower: 2.4, line: 0.5, angle: 34, hot: false, grey: '#2a2a2d' },
  glass: { base: '#060302', rim: 0.9, alpha: 0.28, fresAlpha: 0.4, fresPower: 2.2, line: 0.38, angle: 40, hot: false, grey: '#3a3b40' },
  tyre: { base: '#050302', rim: 0.6, alpha: 0.45, fresAlpha: 0.4, line: 0.22, angle: 52, hot: false, grey: '#1c1c1e' },
  rim: { base: '#1a0e06', rim: 1.4, alpha: 0.4, fresAlpha: 0.4, fresPower: 2.0, line: 0.55, angle: 40, hot: true, grey: '#8a8a8e' },
  detail: { base: '#160b04', rim: 1.6, alpha: 0.42, fresAlpha: 0.5, fresPower: 2.0, line: 0.8, angle: 28, hot: true, grey: '#c8c8cc' },
}

/** the interior group of a split part (seats, dashboard, the inside of the doors, the underbody): ghosted internals, no lines */
export const INTERIOR_LOOK: HoloLook = { base: '#0a0502', rim: 0.25, alpha: 0.035, fresAlpha: 0.05, fresPower: 2.5 }

/** parts smaller than this are always kept whole (lamps, handles, plates): only the big shells are split into exterior / interior */
export const SPLIT_MIN_TRIANGLES = 600

export type { Appearance }

/** A geometry split in two groups that share the ORIGINAL vertex buffers: group 0 = triangles seen from outside, group 1 = interior. */
export interface SplitGeometry {
  geometry: THREE.BufferGeometry
  exteriorTriangles: number
  interiorTriangles: number
  /** crease edges touching the exterior triangles (see exteriorEdges) */
  edges: THREE.BufferGeometry
}

/**
 * Reorder a COPY of the index so the exterior triangles come first, and describe the two runs as geometry groups. The attributes are
 * shared, not copied, and `source` is never modified: the original index stays as the file made it.
 */
export function splitByMask(source: THREE.BufferGeometry, mask: Uint8Array, edgeAngle: number): SplitGeometry {
  const src = source.index
  const pos = source.getAttribute('position')
  const tris = (src ? src.count : pos.count) / 3
  if (mask.length !== tris) throw new Error(`mask has ${mask.length} entries for ${tris} triangles`)
  const exterior: number[] = []
  const interior: number[] = []
  for (let t = 0; t < tris; t++) {
    const into = mask[t] ? exterior : interior
    for (let k = 0; k < 3; k++) into.push(src ? src.getX(t * 3 + k) : t * 3 + k)
  }
  const make = (index: number[]) => {
    const g = new THREE.BufferGeometry()
    for (const name of Object.keys(source.attributes)) g.setAttribute(name, source.getAttribute(name))
    g.setIndex(index)
    return g
  }
  const geometry = make([...exterior, ...interior])
  geometry.clearGroups()
  if (exterior.length) geometry.addGroup(0, exterior.length, 0)
  if (interior.length) geometry.addGroup(exterior.length, interior.length, 1)
  const edges = exteriorEdges(source, mask, edgeAngle)
  return { geometry, exteriorTriangles: exterior.length / 3, interiorTriangles: interior.length / 3, edges }
}

/**
 * Crease edges of a geometry, keeping only those that touch at least one EXTERIOR triangle. Computed on the whole mesh, so a boundary
 * created by the mask (where interior triangles were taken away) is never drawn as a line: only true creases and true open borders.
 */
export function exteriorEdges(source: THREE.BufferGeometry, mask: Uint8Array, angleDeg: number): THREE.BufferGeometry {
  const pos = source.getAttribute('position')
  const idx = source.index
  const tris = (idx ? idx.count : pos.count) / 3
  const key = (i: number) => `${Math.round(pos.getX(i) * 1000)},${Math.round(pos.getY(i) * 1000)},${Math.round(pos.getZ(i) * 1000)}`
  const normals: THREE.Vector3[] = []
  const edges = new Map<string, { a: number; b: number; faces: number[] }>()
  const a = new THREE.Vector3()
  const b = new THREE.Vector3()
  const c = new THREE.Vector3()
  for (let t = 0; t < tris; t++) {
    const v = [0, 1, 2].map((k) => (idx ? idx.getX(t * 3 + k) : t * 3 + k))
    a.fromBufferAttribute(pos, v[0]!)
    b.fromBufferAttribute(pos, v[1]!)
    c.fromBufferAttribute(pos, v[2]!)
    normals.push(new THREE.Vector3().subVectors(c, b).cross(new THREE.Vector3().subVectors(a, b)).normalize())
    const ks = v.map(key)
    for (let k = 0; k < 3; k++) {
      const i0 = k
      const i1 = (k + 1) % 3
      const k0 = ks[i0]!
      const k1 = ks[i1]!
      if (k0 === k1) continue
      const ek = k0 < k1 ? `${k0}|${k1}` : `${k1}|${k0}`
      const e = edges.get(ek)
      if (e) e.faces.push(t)
      else edges.set(ek, { a: v[i0]!, b: v[i1]!, faces: [t] })
    }
  }
  const cos = Math.cos((angleDeg * Math.PI) / 180)
  const out: number[] = []
  for (const e of edges.values()) {
    const touchesExterior = e.faces.some((f) => mask[f])
    if (!touchesExterior) continue
    const open = e.faces.length === 1
    const crease = e.faces.length === 2 && normals[e.faces[0]!]!.dot(normals[e.faces[1]!]!) <= cos
    if (!open && !crease) continue
    out.push(pos.getX(e.a), pos.getY(e.a), pos.getZ(e.a), pos.getX(e.b), pos.getY(e.b), pos.getZ(e.b))
  }
  const g = new THREE.BufferGeometry()
  g.setAttribute('position', new THREE.Float32BufferAttribute(out, 3))
  return g
}

export interface PartVariants {
  mesh: THREE.Mesh
  role: PartRole
  /** the file's own material(s): never modified, so the original look is always recoverable */
  original: THREE.Material | THREE.Material[]
  /** the file's own geometry (the hologram of a split part draws a reordered copy of its index instead) */
  geometry: THREE.BufferGeometry
  /** hologram material of the exterior triangles (or of the whole part when it is not split) */
  holo: THREE.Material
  /** hologram material of the interior triangles (only when split) */
  holoInner?: THREE.Material
  split?: SplitGeometry
  grey: THREE.Material
  lines: THREE.LineSegments[]
}

export interface VariantHooks {
  /** register a created GPU resource for disposal by the scene */
  track(d: { dispose(): void }): void
  /** register an amber line material so the scan-in reveal can fade it */
  fade(mat: THREE.Material, base: number): void
  /** edge geometries are shared between the car and its floor reflection */
  edgeCache: Map<THREE.BufferGeometry, Map<number, THREE.EdgesGeometry>>
  /** split geometries too */
  splitCache?: Map<THREE.BufferGeometry, SplitGeometry>
}

/**
 * Give every mesh of `root` its alternative looks next to its original one: the hologram (a separate, dark, semi-transparent material
 * plus amber lines on the real panel creases; for big shells with a `masks` entry, the interior triangles get a ghost material and no
 * lines) and a neutral grey. Nothing of the original is touched. `k` scales the opacities (the floor reflection uses a small k).
 */
export function prepareVariants(root: THREE.Object3D, asset: VehicleAsset, shared: HoloUniforms, k: number, hooks: VariantHooks, masks?: ExteriorMasks): PartVariants[] {
  const out: PartVariants[] = []
  for (const mesh of meshesOf(root)) {
    const first = Array.isArray(mesh.material) ? mesh.material[0] : mesh.material
    const role = roleOf(asset, first?.name)
    const look = PART_LOOKS[role]
    // a file with its own vertex normals is rim-lit with them (smooth); one without keeps the flat per-face fallback
    const smooth = !!mesh.geometry.getAttribute('normal')
    const holo = makeHoloMaterial(shared, { ...look, alpha: look.alpha * (k < 1 ? 0.8 : 1), smooth })
    // double-sided: some files (model A) have single-sided panels with inverted normals that would vanish when back-face culled
    const grey = new THREE.MeshStandardMaterial({ color: look.grey, roughness: 0.78, metalness: 0.08, side: THREE.DoubleSide })
    hooks.track(holo)
    hooks.track(grey)

    let split: SplitGeometry | undefined
    const mask = masks?.get(mesh.geometry)
    if (mask && mask.some((v) => v === 0)) {
      const cache = (hooks.splitCache ??= new Map())
      split = cache.get(mesh.geometry)
      if (!split) {
        split = splitByMask(mesh.geometry, mask, look.angle)
        cache.set(mesh.geometry, split)
        hooks.track(split.geometry)
        hooks.track(split.edges)
      }
    }
    let holoInner: THREE.Material | undefined
    if (split) {
      holoInner = makeHoloMaterial(shared, { ...INTERIOR_LOOK, smooth })
      hooks.track(holoInner)
    }

    let edges: THREE.BufferGeometry | undefined = split?.edges
    if (!edges) {
      let byAngle = hooks.edgeCache.get(mesh.geometry)
      if (!byAngle) hooks.edgeCache.set(mesh.geometry, (byAngle = new Map()))
      let e = byAngle.get(look.angle)
      if (!e) {
        e = new THREE.EdgesGeometry(mesh.geometry, look.angle)
        byAngle.set(look.angle, e)
        hooks.track(e)
      }
      edges = e
    }
    const lineMat = makeLineMaterial(look.line * k, look.hot)
    hooks.track(lineMat)
    hooks.fade(lineMat, look.line * k)
    const line = new THREE.LineSegments(edges, lineMat)
    line.visible = false
    mesh.add(line)
    out.push({ mesh, role, original: mesh.material, geometry: mesh.geometry, holo, holoInner, split, grey, lines: [line] })
  }
  return out
}

const DIAG_EXTERIOR = new THREE.MeshBasicMaterial({ color: 0x35d07f, side: THREE.DoubleSide, transparent: true, opacity: 0.35, depthWrite: false })
const DIAG_INTERIOR = new THREE.MeshBasicMaterial({ color: 0xe0443a, side: THREE.DoubleSide, transparent: true, opacity: 0.55, depthWrite: false })

export function applyAppearance(variants: PartVariants[], appearance: Appearance) {
  for (const v of variants) {
    if (appearance === 'split') {
      // diagnostic: where did the visibility pass put each triangle?
      v.mesh.geometry = v.split ? v.split.geometry : v.geometry
      v.mesh.material = v.split ? [DIAG_EXTERIOR, DIAG_INTERIOR] : DIAG_EXTERIOR
      for (const l of v.lines) l.visible = false
      continue
    }
    if (appearance === 'hologram') {
      v.mesh.geometry = v.split ? v.split.geometry : v.geometry
      v.mesh.material = v.split && v.holoInner ? [v.holo, v.holoInner] : v.holo
    } else {
      v.mesh.geometry = v.geometry
      v.mesh.material = appearance === 'grey' ? v.grey : v.original
    }
    for (const l of v.lines) l.visible = appearance === 'hologram'
  }
}
