import * as THREE from 'three'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

// WebGL does not exist in jsdom: the renderer is replaced by a recorder, everything else in three is the real thing
const renderer = { dispose: vi.fn(), forceContextLoss: vi.fn(), render: vi.fn(), setClearColor: vi.fn(), setPixelRatio: vi.fn(), setSize: vi.fn() }
vi.mock('three', async (orig) => {
  const t = await orig<typeof import('three')>()
  class FakeRenderer {
    constructor() {
      return renderer as unknown as FakeRenderer
    }
  }
  return { ...t, WebGLRenderer: FakeRenderer }
})

// the GLB loader: fails by default (no network in jsdom, so "missing model" is the normal case); a test can hand it a scene
const gltf = { scene: null as THREE.Group | null }
vi.mock('three/examples/jsm/loaders/GLTFLoader.js', () => ({
  GLTFLoader: class {
    async loadAsync() {
      if (!gltf.scene) throw new Error('no such model')
      return { scene: gltf.scene, asset: { generator: 'test' } }
    }
  },
}))

import { buildBodyGeometry, buildBodyLines, buildDetailLines, buildWheel, DIM, PLACEHOLDER_ID } from './fitPlaceholder'
import { BASE_YAW, SWING, VehicleScene, type SceneEvent } from './VehicleScene'

const canvas = () => {
  const c = document.createElement('canvas')
  Object.defineProperty(c, 'clientWidth', { value: 800 })
  Object.defineProperty(c, 'clientHeight', { value: 500 })
  return c
}

describe('placeholder geometry (not a Honda Fit GD model)', () => {
  it('has the proportions it claims and is labelled as a placeholder', () => {
    const g = buildBodyGeometry()
    g.computeBoundingBox()
    const b = g.boundingBox!
    expect(b.max.x - b.min.x).toBeCloseTo(DIM.length, 1)
    expect(b.max.z - b.min.z).toBeLessThanOrEqual(DIM.width + 0.01)
    expect(b.max.y).toBeLessThan(1.7)
    expect(PLACEHOLDER_ID).toMatch(/placeholder/)
    expect(PLACEHOLDER_ID).toMatch(/not-honda-fit-gd/)
  })

  it('has four wheels, door cuts, lamps and body lines', () => {
    expect(buildWheel().positions).toHaveLength(4)
    expect(buildDetailLines().length).toBeGreaterThan(20)
    expect(buildBodyLines().getAttribute('position').count).toBeGreaterThan(100)
  })
})

describe('VehicleScene', () => {
  let raf: Array<FrameRequestCallback>
  beforeEach(() => {
    Object.values(renderer).forEach((f) => f.mockClear())
    raf = []
    vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback) => (raf.push(cb), raf.length))
    vi.stubGlobal('cancelAnimationFrame', () => {})
  })
  afterEach(() => vi.unstubAllGlobals())

  it('renders a first frame and reports ready', () => {
    const events: SceneEvent[] = []
    const s = new VehicleScene(canvas(), { reduced: false, onEvent: (e) => events.push(e) })
    expect(renderer.render).toHaveBeenCalled()
    expect(events).toContain('ready')
    s.dispose()
  })

  it('rotates ambiently, slowly, inside its limits', () => {
    const s = new VehicleScene(canvas(), { reduced: false })
    const yaws = Array.from({ length: 200 }, (_, i) => s.yaw(i * 0.5))
    expect(Math.max(...yaws) - BASE_YAW).toBeLessThanOrEqual(SWING.amplitude + 1e-9)
    expect(BASE_YAW - Math.min(...yaws)).toBeLessThanOrEqual(SWING.amplitude + 1e-9)
    // slow: the whole swing takes tens of seconds (well under 0.1 rad per second)
    const fastest = Math.max(...yaws.slice(1).map((y, i) => Math.abs(y - yaws[i]!) / 0.5))
    expect(fastest).toBeLessThan(0.1)
    s.dispose()
  })

  it('reduced motion: one still frame, no loop, no rotation', () => {
    const s = new VehicleScene(canvas(), { reduced: true })
    s.start()
    expect(raf).toHaveLength(0)
    expect(s.isRunning).toBe(false)
    expect(s.yaw(12.3)).toBe(BASE_YAW)
    s.dispose()
  })

  it('can be paused and resumed (no frame is requested while stopped)', () => {
    const s = new VehicleScene(canvas(), { reduced: false })
    s.start()
    expect(s.isRunning).toBe(true)
    expect(raf).toHaveLength(1)
    s.stop()
    raf[0]!(performance.now())
    expect(raf).toHaveLength(1) // the tick bailed out without scheduling another
    s.setMotion(false)
    expect(s.yaw(5)).toBe(BASE_YAW)
    s.dispose()
  })

  it('a lost WebGL context stops the loop and is reported; a restored one resumes', () => {
    const c = canvas()
    const events: SceneEvent[] = []
    const s = new VehicleScene(c, { reduced: false, onEvent: (e) => events.push(e) })
    s.start()
    const lost = new Event('webglcontextlost', { cancelable: true })
    c.dispatchEvent(lost)
    expect(lost.defaultPrevented).toBe(true)
    expect(s.isRunning).toBe(false)
    expect(events).toContain('lost')
    c.dispatchEvent(new Event('webglcontextrestored'))
    expect(events).toContain('restored')
    expect(s.isRunning).toBe(true)
    s.dispose()
  })

  it('dispose releases the renderer, the context and every geometry and material, and is idempotent', () => {
    const geomDispose = vi.spyOn(THREE.BufferGeometry.prototype, 'dispose')
    const matDispose = vi.spyOn(THREE.Material.prototype, 'dispose')
    const c = canvas()
    const s = new VehicleScene(c, { reduced: false })
    s.start()
    s.dispose()
    expect(renderer.dispose).toHaveBeenCalledTimes(1)
    expect(renderer.forceContextLoss).toHaveBeenCalledTimes(1)
    expect(geomDispose.mock.calls.length).toBeGreaterThan(5)
    expect(matDispose.mock.calls.length).toBeGreaterThan(5)
    expect(s.isRunning).toBe(false)
    s.dispose()
    expect(renderer.dispose).toHaveBeenCalledTimes(1)
    geomDispose.mockRestore()
    matDispose.mockRestore()
  })

  it('a missing model falls back to the placeholder and says so', async () => {
    const events: SceneEvent[] = []
    const s = new VehicleScene(canvas(), { reduced: true, modelUrl: '/models/does-not-exist.glb', onEvent: (e) => events.push(e) })
    await vi.waitFor(() => expect(events).toContain('model-missing'))
    expect(s.model).toBe(PLACEHOLDER_ID)
    s.dispose()
  })

  it('a loaded model replaces the placeholder: events, stats, reversible looks, and both are released on dispose', async () => {
    const car = new THREE.Group()
    car.add(
      Object.assign(new THREE.Mesh(new THREE.BoxGeometry(4, 1.2, 1.7), new THREE.MeshStandardMaterial()), { name: 'body' }),
      Object.assign(new THREE.Mesh(new THREE.BoxGeometry(0.6, 0.6, 0.2), new THREE.MeshStandardMaterial()), { name: 'wheel' }),
    )
    gltf.scene = car
    const geo = vi.spyOn(THREE.BufferGeometry.prototype, 'dispose')
    const events: SceneEvent[] = []
    const s = new VehicleScene(canvas(), { reduced: true, modelUrl: '/__local_vehicle/model-c.glb', assetId: 'model-c', onEvent: (e) => events.push(e) })
    await vi.waitFor(() => expect(events).toContain('model-loaded'))
    expect(events).toContain('model-loading')
    expect(s.model).toBe('model-c')
    expect(s.stats().model?.meshes).toBe(2)
    const placeholderDisposals = geo.mock.calls.length
    expect(placeholderDisposals).toBeGreaterThan(5) // the procedural car's resources were released when the model took over
    for (const look of ['grey', 'original', 'hologram'] as const) expect(() => s.setAppearance(look)).not.toThrow()
    s.resetView()
    s.dispose()
    expect(geo.mock.calls.length).toBeGreaterThan(placeholderDisposals) // the model's geometries and edge lines too
    geo.mockRestore()
    gltf.scene = null
  })

  it('a failing model leaves the placeholder on show and says so', async () => {
    gltf.scene = null
    const events: SceneEvent[] = []
    const s = new VehicleScene(canvas(), { reduced: true, modelUrl: '/__local_vehicle/model-c.glb', assetId: 'model-c', onEvent: (e) => events.push(e) })
    await vi.waitFor(() => expect(events).toContain('model-missing'))
    expect(s.model).toBe(PLACEHOLDER_ID)
    expect(events).not.toContain('model-loaded')
    s.dispose()
  })

  it('development drag turns the car and reset brings the three-quarter view back', () => {
    const c = canvas()
    const s = new VehicleScene(c, { reduced: true, devControls: true })
    c.dispatchEvent(Object.assign(new Event('pointerdown'), { clientX: 100, pointerId: 1 }))
    c.dispatchEvent(Object.assign(new Event('pointermove'), { clientX: 220 }))
    c.dispatchEvent(new Event('pointerup'))
    expect(Number(c.dataset.yaw)).not.toBeCloseTo(BASE_YAW, 2)
    s.resetView()
    expect(Number(c.dataset.yaw)).toBeCloseTo(BASE_YAW, 3)
    s.dispose()
  })
})
