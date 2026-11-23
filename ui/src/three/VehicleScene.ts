import * as THREE from 'three'
import { buildBodyGeometry, buildBodyLines, buildDetailLines, buildWheel, PLACEHOLDER_ID } from './fitPlaceholder'
import { makeHoloBodyMaterial, makeLineMaterial, makeUniforms, type HoloUniforms } from './hologram'
import { BASE_YAW, CAMERA_PRESETS, CAMERA_REFINED, SWING, VIEW_YAW } from './cameraPresets'
import { getAsset, roleOf, type Appearance, type VehicleAssetId } from './vehicleAssets'
import { applyAppearance, loadVehicleGlb, prepareVariants, SPLIT_MIN_TRIANGLES, type LoadedVehicle, type ModelStats, type PartVariants } from './vehicleModel'
import { canClassify, computeExteriorMasks, type ExteriorMasks } from './visibility'

export type SceneEvent = 'ready' | 'lost' | 'restored' | 'model-loading' | 'model-loaded' | 'model-missing'

export interface SceneOptions {
  /** reduced motion: one still frame, no loop, no rotation */
  reduced: boolean
  /** a GLB to show instead of the procedural car. Local preview assets come from the dev server only; when loading fails the
   *  placeholder stays and `model-missing` is reported */
  modelUrl?: string
  /** which asset `modelUrl` is (orientation of the file, part roles): see vehicleAssets.ts */
  assetId?: VehicleAssetId
  appearance?: Appearance
  /** development only: drag the car to turn it */
  devControls?: boolean
  /** manual yaw from the three-quarter view, radians; switches the ambient swing off */
  initialYawOffset?: number
  /** development: a named camera (cameraPresets.ts) and a named view (front34, side, front, rear34) */
  camera?: string
  view?: string
  /** development only: write measurements (draw calls, triangles, load time...) into the canvas dataset */
  publishStats?: boolean
  onEvent?: (e: SceneEvent) => void
}

// the camera and view constants live in cameraPresets.ts; re-exported for the callers and tests that already import them from here
export { BASE_YAW, SWING }
const REVEAL_SECONDS = 1.4

interface Fade {
  mat: THREE.Material
  base: number
}

export interface SceneStats {
  calls: number
  triangles: number
  geometries: number
  textures: number
  programs: number
  frames: number
  model: ModelStats | null
  /** triangles of the split shells: seen from outside / ghosted interior, and what the visibility pass cost */
  exteriorTriangles: number
  interiorTriangles: number
  visibilityMs: number
}

/**
 * The Three.js side of the vehicle: owns the renderer, the scene graph and the loop, and releases every GPU resource in
 * dispose(). No React in here; HolographicVehicle.tsx is the thin component around it.
 */
export class VehicleScene {
  private renderer: THREE.WebGLRenderer
  private scene = new THREE.Scene()
  private camera = new THREE.PerspectiveCamera(CAMERA_REFINED.fov, 1.6, 0.1, 60)
  private car = new THREE.Group()
  private mirror = new THREE.Group()
  private uniforms: HoloUniforms = makeUniforms()
  private mirrorUniforms: HoloUniforms = makeUniforms()
  private fades: Fade[] = []
  private mirrorFades: Fade[] = []
  /** GPU resources of the procedural car / of a loaded model: released separately when the model replaces the placeholder */
  private phDisposables: Array<{ dispose(): void }> = []
  private modelDisposables: Array<{ dispose(): void }> = []
  private variants: PartVariants[] = []
  private loaded: LoadedVehicle | null = null
  private raf = 0
  private running = false
  private motion: boolean
  private t0 = performance.now()
  private revealFrom = 0
  private revealTo = 0
  private revealStart = 0
  private revealed = 0
  private disposed = false
  private appearance: Appearance
  private modelState: 'placeholder' | 'loading' | 'loaded' | 'missing' = 'placeholder'
  private manual: boolean
  private userYaw: number
  private dragging = false
  private lastX = 0
  private lastPublish = 0
  private maskMs = 0
  frames = 0

  constructor(private canvas: HTMLCanvasElement, private opts: SceneOptions) {
    this.renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true, powerPreference: 'high-performance' })
    this.renderer.setClearColor(0x000000, 0)
    this.motion = !opts.reduced
    this.appearance = opts.appearance ?? 'hologram'
    const viewYaw = opts.view !== undefined ? VIEW_YAW[opts.view] : undefined
    this.userYaw = opts.initialYawOffset ?? (viewYaw !== undefined ? viewYaw - BASE_YAW : 0)
    this.manual = opts.initialYawOffset !== undefined || viewYaw !== undefined
    const preset = (opts.camera && CAMERA_PRESETS[opts.camera]) || CAMERA_REFINED
    this.camera.fov = preset.fov
    this.camera.position.set(...preset.position)
    this.camera.lookAt(...preset.target)
    // depth cue (surfaces: shader uniforms; amber lines: scene fog towards black): the near side of the car reads first
    const dist = new THREE.Vector3(...preset.position).length()
    for (const u of [this.uniforms, this.mirrorUniforms]) {
      u.uNear.value = dist - 1.1
      u.uFar.value = dist + 2.3
    }
    this.scene.fog = new THREE.Fog(0x000000, dist - 1.1, dist + 5.5)
    this.mirrorUniforms.uOpacity.value = 0.12
    // lights only matter for the grey / original looks (the hologram and the amber lines are unlit)
    this.scene.add(new THREE.HemisphereLight(0xffffff, 0x3a3a42, 1.1))
    const sun = new THREE.DirectionalLight(0xffffff, 2.2)
    sun.position.set(4, 7, 5)
    this.scene.add(sun)
    this.build()
    canvas.addEventListener('webglcontextlost', this.onLost)
    canvas.addEventListener('webglcontextrestored', this.onRestored)
    if (opts.devControls) {
      canvas.style.touchAction = 'none'
      canvas.addEventListener('pointerdown', this.onPointerDown)
      canvas.addEventListener('pointermove', this.onPointerMove)
      canvas.addEventListener('pointerup', this.onPointerUp)
      canvas.addEventListener('pointercancel', this.onPointerUp)
    }
    this.resize()
    this.applyPose(0)
    this.applyReveal(opts.reduced ? 1 : 0)
    if (opts.reduced) this.revealed = this.revealTo = 1
    this.renderOnce()
    this.publish(true)
    opts.onEvent?.('ready')
    if (opts.modelUrl) void this.loadModel(opts.modelUrl, opts.assetId ?? 'placeholder')
  }

  /** the model on show: the procedural placeholder's id until a real one is installed */
  get model(): string {
    return this.loaded ? (this.opts.assetId ?? 'model') : PLACEHOLDER_ID
  }

  private track<T extends { dispose(): void }>(x: T, list: Array<{ dispose(): void }> = this.phDisposables): T {
    list.push(x)
    return x
  }

  private build() {
    const body = this.track(buildBodyGeometry())
    const edges = this.track(buildBodyLines())
    const details = buildDetailLines().map((g) => this.track(g))
    const wheel = buildWheel()
    for (const g of [wheel.tyre, wheel.rim, wheel.spokes]) this.track(g)
    const tyreEdges = this.track(new THREE.EdgesGeometry(wheel.tyre, 30))

    const make = (group: THREE.Group, u: HoloUniforms, fades: Fade[], k: number) => {
      const bodyMat = this.track(makeHoloBodyMaterial(u))
      group.add(new THREE.Mesh(body, bodyMat))
      const line = (g: THREE.BufferGeometry, base: number, hot = false, loop = false) => {
        const m = this.track(makeLineMaterial(base * k, hot))
        fades.push({ mat: m, base: base * k })
        group.add(loop ? new THREE.LineLoop(g, m) : new THREE.LineSegments(g, m))
      }
      line(edges, 0.6, true)
      details.forEach((g) => group.add(new THREE.Line(g, this.fadeLine(fades, k, 0.7))))
      for (const [x, y, z] of wheel.positions) {
        const w = new THREE.Group()
        w.position.set(x, y, z)
        const tm = this.fadeLine(fades, k, 0.6)
        w.add(new THREE.LineSegments(tyreEdges, tm))
        const rm = this.fadeLine(fades, k, 0.9)
        w.add(new THREE.LineLoop(wheel.rim, rm))
        w.add(new THREE.LineSegments(wheel.spokes, rm))
        group.add(w)
      }
    }
    make(this.car, this.uniforms, this.fades, 1)
    make(this.mirror, this.mirrorUniforms, this.mirrorFades, 0.14)
    this.mirror.scale.y = -1
    this.scene.add(this.car, this.mirror)
  }

  private fadeLine(fades: Fade[], k: number, base: number): THREE.LineBasicMaterial {
    const m = this.track(makeLineMaterial(base * k))
    fades.push({ mat: m, base: base * k })
    return m
  }

  // ───────────── loaded model ─────────────
  private async loadModel(url: string, id: VehicleAssetId) {
    this.modelState = 'loading'
    this.opts.onEvent?.('model-loading')
    this.publish(true)
    try {
      const loaded = await loadVehicleGlb(url, id)
      if (this.disposed) {
        loaded.dispose()
        return
      }
      this.install(loaded, id)
      this.modelState = 'loaded'
      this.opts.onEvent?.('model-loaded')
    } catch {
      if (this.disposed) return
      this.modelState = 'missing'
      this.opts.onEvent?.('model-missing')
    }
    this.publish(true)
  }

  /** swap the procedural car for the loaded one: the original materials stay on its meshes, the looks are separate instances */
  private install(loaded: LoadedVehicle, id: VehicleAssetId) {
    this.scene.remove(this.car, this.mirror)
    for (const d of this.phDisposables) d.dispose()
    this.phDisposables = []
    this.fades = []
    this.mirrorFades = []
    this.car = new THREE.Group()
    this.mirror = new THREE.Group()
    this.car.add(loaded.root)
    const reflection = loaded.root.clone(true)
    this.mirror.add(reflection)
    this.mirror.scale.y = -1
    const asset = getAsset(id)
    const hooks = (fades: Fade[]) => ({
      track: (d: { dispose(): void }) => void this.track(d, this.modelDisposables),
      fade: (mat: THREE.Material, base: number) => void fades.push({ mat, base }),
      edgeCache: sharedEdges,
    })
    const sharedEdges = new Map<THREE.BufferGeometry, Map<number, THREE.EdgesGeometry>>()
    const sharedSplits = new Map<THREE.BufferGeometry, import('./vehicleModel').SplitGeometry>()
    // which triangles of the big shells are seen from outside: the rest (seats, dashboard, door insides, underbody) becomes a ghost
    let masks: ExteriorMasks | undefined
    const t0 = performance.now()
    if (canClassify(this.renderer)) {
      try {
        masks = computeExteriorMasks(this.renderer, loaded.root, {
          classify: (m) => {
            const role = roleOf(asset, (Array.isArray(m.material) ? m.material[0] : m.material)?.name)
            const g = m.geometry
            return (role === 'body' || role === 'trim') && (g.index ? g.index.count : g.getAttribute('position').count) / 3 >= SPLIT_MIN_TRIANGLES
          },
        })
      } catch {
        masks = undefined // the pass is a refinement: without it the hologram simply keeps every triangle
      }
    }
    this.maskMs = performance.now() - t0
    const shared = (fades: Fade[]) => ({ ...hooks(fades), edgeCache: sharedEdges, splitCache: sharedSplits })
    this.variants = [
      ...prepareVariants(loaded.root, asset, this.uniforms, 1, shared(this.fades), masks),
      ...prepareVariants(reflection, asset, this.mirrorUniforms, 0.14, shared(this.mirrorFades), masks),
    ]
    this.loaded = loaded
    this.scene.add(this.car, this.mirror)
    this.setAppearance(this.appearance)
    this.applyReveal(this.revealed)
    this.applyPose((performance.now() - this.t0) / 1000)
    this.renderOnce()
  }

  /** hologram (amber, translucent) / grey (neutral, to judge the shape) / original (the file's own materials). Reversible at any time. */
  setAppearance(a: Appearance) {
    this.appearance = a
    if (this.loaded) {
      applyAppearance(this.variants, a)
      this.mirror.visible = a === 'hologram'
    }
    if (!this.running) this.renderOnce()
    this.publish(true)
  }

  /** back to the three-quarter view with the ambient swing */
  resetView() {
    this.userYaw = 0
    this.manual = false
    this.applyPose((performance.now() - this.t0) / 1000)
    if (!this.running) this.renderOnce()
  }

  stats(): SceneStats {
    const info = this.renderer.info as THREE.WebGLInfo | undefined
    const splits = new Set(this.variants.map((v) => v.split).filter((s): s is NonNullable<typeof s> => !!s))
    let exteriorTriangles = 0
    let interiorTriangles = 0
    for (const sp of splits) {
      exteriorTriangles += sp.exteriorTriangles
      interiorTriangles += sp.interiorTriangles
    }
    return {
      calls: info?.render.calls ?? 0,
      triangles: info?.render.triangles ?? 0,
      geometries: info?.memory.geometries ?? 0,
      textures: info?.memory.textures ?? 0,
      programs: info?.programs?.length ?? 0,
      frames: this.frames,
      model: this.loaded?.stats ?? null,
      exteriorTriangles,
      interiorTriangles,
      visibilityMs: Math.round(this.maskMs),
    }
  }

  private publish(force = false) {
    if (!this.opts.publishStats) return
    const now = performance.now()
    if (!force && now - this.lastPublish < 1000) return
    this.lastPublish = now
    const s = this.stats()
    const d = this.canvas.dataset
    d.vehicleAsset = this.opts.assetId ?? 'placeholder'
    d.modelState = this.modelState
    d.appearance = this.appearance
    d.calls = String(s.calls)
    d.triangles = String(s.triangles)
    d.geometries = String(s.geometries)
    d.textures = String(s.textures)
    d.programs = String(s.programs)
    d.exteriorTris = String(s.exteriorTriangles)
    d.interiorTris = String(s.interiorTriangles)
    d.visibilityMs = String(s.visibilityMs)
    if (s.model) {
      d.modelTris = String(s.model.triangles)
      d.modelMeshes = String(s.model.meshes)
      d.modelLoadMs = String(Math.round(s.model.loadMs))
      d.modelSize = [s.model.lengthM, s.model.widthM, s.model.heightM].map((v) => v.toFixed(3)).join('x')
    }
  }

  // ───────────── events ─────────────
  private onLost = (e: Event) => {
    e.preventDefault()
    this.stop()
    this.opts.onEvent?.('lost')
  }
  private onRestored = () => {
    this.opts.onEvent?.('restored')
    this.renderOnce()
    if (this.motion) this.start()
  }
  private onPointerDown = (e: PointerEvent) => {
    this.dragging = true
    this.manual = true
    this.lastX = e.clientX
    this.canvas.setPointerCapture?.(e.pointerId)
  }
  private onPointerMove = (e: PointerEvent) => {
    if (!this.dragging) return
    this.userYaw += (e.clientX - this.lastX) * 0.008
    this.lastX = e.clientX
    this.applyPose((performance.now() - this.t0) / 1000)
    if (!this.running) this.renderOnce()
  }
  private onPointerUp = () => {
    this.dragging = false
  }

  resize() {
    const w = Math.max(1, this.canvas.clientWidth)
    const h = Math.max(1, this.canvas.clientHeight)
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5))
    this.renderer.setSize(w, h, false)
    this.camera.aspect = w / h
    this.camera.updateProjectionMatrix()
    if (!this.running) this.renderOnce()
  }

  /** target 1 = scan the car in (fades in over ~1.4 s), 0 = hide it */
  setReveal(target: number, immediate = false) {
    this.revealFrom = this.revealed
    this.revealTo = target
    this.revealStart = performance.now()
    if (immediate || this.opts.reduced) {
      this.revealed = this.revealTo = target
      this.applyReveal(target)
      if (!this.running) this.renderOnce()
    }
  }

  setMotion(on: boolean) {
    this.motion = on && !this.opts.reduced
    if (!this.motion && !this.running) this.renderOnce()
  }

  private applyReveal(r: number) {
    this.uniforms.uReveal.value = r
    this.mirrorUniforms.uReveal.value = r
    for (const f of this.fades) f.mat.opacity = f.base * Math.min(1, r * 1.6)
    for (const f of this.mirrorFades) f.mat.opacity = f.base * Math.min(1, r * 1.6)
  }

  yaw(seconds: number): number {
    if (this.manual) return BASE_YAW + this.userYaw
    if (!this.motion) return BASE_YAW
    return BASE_YAW + Math.sin((seconds / SWING.periodSeconds) * Math.PI * 2) * SWING.amplitude
  }

  private applyPose(seconds: number) {
    const y = this.yaw(seconds)
    this.car.rotation.y = y
    this.mirror.rotation.y = y
    this.canvas.dataset.yaw = y.toFixed(3)
  }

  private renderOnce() {
    if (this.disposed) return
    this.renderer.render(this.scene, this.camera)
  }

  private tick = () => {
    if (!this.running) return
    const now = performance.now()
    const s = (now - this.t0) / 1000
    this.uniforms.uTime.value = s
    this.mirrorUniforms.uTime.value = s
    if (this.revealed !== this.revealTo) {
      const p = Math.min(1, (now - this.revealStart) / 1000 / REVEAL_SECONDS)
      const e = 1 - Math.pow(1 - p, 3)
      this.revealed = this.revealFrom + (this.revealTo - this.revealFrom) * e
      this.applyReveal(this.revealed)
    }
    this.applyPose(s)
    this.renderOnce()
    this.frames++
    this.publish()
    this.raf = requestAnimationFrame(this.tick)
  }

  start() {
    if (this.running || this.disposed || this.opts.reduced) return
    this.running = true
    this.raf = requestAnimationFrame(this.tick)
  }

  stop() {
    this.running = false
    cancelAnimationFrame(this.raf)
  }

  get isRunning() {
    return this.running
  }

  dispose() {
    if (this.disposed) return
    this.disposed = true
    this.stop()
    this.canvas.removeEventListener('webglcontextlost', this.onLost)
    this.canvas.removeEventListener('webglcontextrestored', this.onRestored)
    this.canvas.removeEventListener('pointerdown', this.onPointerDown)
    this.canvas.removeEventListener('pointermove', this.onPointerMove)
    this.canvas.removeEventListener('pointerup', this.onPointerUp)
    this.canvas.removeEventListener('pointercancel', this.onPointerUp)
    for (const d of [...this.phDisposables, ...this.modelDisposables]) d.dispose()
    this.phDisposables = []
    this.modelDisposables = []
    this.loaded?.dispose()
    this.loaded = null
    this.variants = []
    this.scene.clear()
    this.renderer.dispose()
    this.renderer.forceContextLoss()
  }
}
