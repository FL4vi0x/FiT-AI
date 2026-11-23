import * as THREE from 'three'

/**
 * Which triangles of a model are SEEN FROM OUTSIDE? A GPU visibility pass: the model is rendered, opaque, from many viewpoints around
 * and above it into an offscreen target, every triangle painted with its own id, and the pixels of each id are counted over all views.
 * A triangle is "exterior" when a real FRACTION of its area is seen (not a sliver glimpsed through a grille or a wheel arch): that
 * keeps the engine-bay floor and the dashboard shell, which peek out through gaps, in the interior group.
 * What never shows (seats, dashboard, the inside of the doors behind the glass, the underbody) is "interior".
 *
 * Non-destructive: the source geometry is only read. The result is a mask per geometry (1 = exterior, 0 = interior) used to build
 * a reordered, grouped COPY of the index (see splitByMask in vehicleModel.ts); the original index and attributes stay as the file made them.
 */
export type ExteriorMasks = Map<THREE.BufferGeometry, Uint8Array>

const ID_VERT = /* glsl */ `
  attribute float fid; varying float vId;
  void main(){ vId = fid; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`
const ID_FRAG = /* glsl */ `
  varying float vId;
  void main(){
    float id = floor(vId + 0.5);
    gl_FragColor = vec4(mod(id, 256.0) / 255.0, mod(floor(id / 256.0), 256.0) / 255.0, floor(id / 65536.0) / 255.0, 1.0);
  }`

/** viewpoints that matter on stage: all around, at three heights, and from above. Never from below: the underbody is not meant to be seen. */
export function viewDirections(): THREE.Vector3[] {
  const out: THREE.Vector3[] = []
  for (const el of [8, 35, 65]) {
    for (let az = 0; az < 360; az += 45) {
      const e = (el * Math.PI) / 180
      const a = (az * Math.PI) / 180
      out.push(new THREE.Vector3(Math.cos(e) * Math.sin(a), Math.sin(e), Math.cos(e) * Math.cos(a)))
    }
  }
  out.push(new THREE.Vector3(0.001, 1, 0.001).normalize())
  return out
}

/** add the pixels of every triangle id found in one rendered view to `counts` (counts[id - 1]; id 0 is the empty background) */
export function decodeIds(pixels: Uint8Array, counts: Uint32Array) {
  for (let i = 0; i < pixels.length; i += 4) {
    const id = pixels[i]! + pixels[i + 1]! * 256 + pixels[i + 2]! * 65536
    if (id > 0 && id <= counts.length) counts[id - 1]!++
  }
}

/**
 * Decide exterior (1) / interior (0) from the pixel count of a triangle and its area measured in pixels (the area it would cover seen
 * face-on). Seen from several directions, a visible panel accumulates many times its face-on area; a sliver seen through a gap
 * accumulates a small fraction of it. At least one pixel is always required.
 */
export function isExterior(pixels: number, areaPx: number, fraction: number): 0 | 1 {
  return pixels >= Math.max(1, areaPx * fraction) ? 1 : 0
}

export interface VisibilityOptions {
  /** every mesh occludes; only meshes accepted here get a mask (small parts such as lamps and handles are always kept whole) */
  classify: (mesh: THREE.Mesh) => boolean
  size?: number
  /** share of a triangle's face-on area that must be seen (summed over the views) to count as exterior (default 0.4) */
  fraction?: number
}

/** True when this renderer can do the pass (the test doubles and exotic contexts cannot: the caller then keeps every triangle). */
export function canClassify(renderer: unknown): renderer is THREE.WebGLRenderer {
  const r = renderer as Partial<THREE.WebGLRenderer>
  return typeof r.readRenderTargetPixels === 'function' && typeof r.setRenderTarget === 'function'
}

export function computeExteriorMasks(renderer: THREE.WebGLRenderer, root: THREE.Object3D, opts: VisibilityOptions): ExteriorMasks {
  const size = opts.size ?? 512
  const fraction = opts.fraction ?? 0.4
  root.updateMatrixWorld(true)
  const meshes: THREE.Mesh[] = []
  root.traverse((o) => {
    if ((o as THREE.Mesh).isMesh) meshes.push(o as THREE.Mesh)
  })

  // one id-painted, non-indexed copy of every mesh (positions only), placed in world space
  const scene = new THREE.Scene()
  const mat = new THREE.ShaderMaterial({ vertexShader: ID_VERT, fragmentShader: ID_FRAG, side: THREE.DoubleSide })
  const temp: THREE.BufferGeometry[] = []
  const ranges: Array<{ geometry: THREE.BufferGeometry; first: number; count: number; classify: boolean; areas: Float32Array }> = []
  let next = 1
  const seenGeometries = new Set<THREE.BufferGeometry>()
  for (const mesh of meshes) {
    const g = mesh.geometry
    const pos = g.getAttribute('position') as THREE.BufferAttribute
    const index = g.index
    const tris = (index ? index.count : pos.count) / 3
    const p = new Float32Array(tris * 9)
    const f = new Float32Array(tris * 3)
    const areas = new Float32Array(tris) // world-space area of each triangle (m^2)
    const w = [new THREE.Vector3(), new THREE.Vector3(), new THREE.Vector3()]
    for (let t = 0; t < tris; t++) {
      for (let k = 0; k < 3; k++) {
        const v = index ? index.getX(t * 3 + k) : t * 3 + k
        p[t * 9 + k * 3] = pos.getX(v)
        p[t * 9 + k * 3 + 1] = pos.getY(v)
        p[t * 9 + k * 3 + 2] = pos.getZ(v)
        f[t * 3 + k] = next + t
        w[k]!.set(pos.getX(v), pos.getY(v), pos.getZ(v)).applyMatrix4(mesh.matrixWorld)
      }
      areas[t] = new THREE.Vector3().subVectors(w[1]!, w[0]!).cross(new THREE.Vector3().subVectors(w[2]!, w[0]!)).length() / 2
    }
    const tg = new THREE.BufferGeometry()
    tg.setAttribute('position', new THREE.BufferAttribute(p, 3))
    tg.setAttribute('fid', new THREE.BufferAttribute(f, 1))
    temp.push(tg)
    const m = new THREE.Mesh(tg, mat)
    m.matrixAutoUpdate = false
    m.matrix.copy(mesh.matrixWorld)
    m.frustumCulled = false
    scene.add(m)
    // a geometry shared by several meshes (a car and its reflection) is classified once, from the first
    if (!seenGeometries.has(g)) {
      seenGeometries.add(g)
      ranges.push({ geometry: g, first: next, count: tris, classify: opts.classify(mesh), areas })
    }
    next += tris
  }
  const counts = new Uint32Array(next)

  const box = new THREE.Box3().setFromObject(root, true)
  const centre = box.getCenter(new THREE.Vector3())
  const radius = box.getSize(new THREE.Vector3()).length() / 2
  const cam = new THREE.OrthographicCamera(-radius, radius, radius, -radius, 0.1, radius * 4)
  const target = new THREE.WebGLRenderTarget(size, size, { minFilter: THREE.NearestFilter, magFilter: THREE.NearestFilter, depthBuffer: true })
  const pixels = new Uint8Array(size * size * 4)

  const prevTarget = renderer.getRenderTarget()
  const prevColor = new THREE.Color()
  renderer.getClearColor(prevColor)
  const prevAlpha = renderer.getClearAlpha()
  renderer.setClearColor(0x000000, 1)
  try {
    for (const dir of viewDirections()) {
      cam.position.copy(centre).addScaledVector(dir, radius * 2)
      cam.up.set(0, Math.abs(dir.y) > 0.99 ? 0 : 1, Math.abs(dir.y) > 0.99 ? -1 : 0)
      cam.lookAt(centre)
      cam.updateMatrixWorld(true)
      renderer.setRenderTarget(target)
      renderer.render(scene, cam)
      renderer.readRenderTargetPixels(target, 0, 0, size, size, pixels)
      decodeIds(pixels, counts)
    }
  } finally {
    renderer.setRenderTarget(prevTarget)
    renderer.setClearColor(prevColor, prevAlpha)
    target.dispose()
    mat.dispose()
    for (const g of temp) g.dispose()
  }

  const pixelArea = ((2 * radius) / size) ** 2 // the area one pixel covers in the orthographic views (m^2)
  const masks: ExteriorMasks = new Map()
  for (const r of ranges) {
    if (!r.classify) continue
    const mask = new Uint8Array(r.count)
    for (let t = 0; t < r.count; t++) mask[t] = isExterior(counts[r.first + t - 1] ?? 0, r.areas[t]! / pixelArea, fraction)
    masks.set(r.geometry, mask)
  }
  return masks
}
