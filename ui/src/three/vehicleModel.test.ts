import * as THREE from 'three'
import { beforeEach, describe, expect, it, vi } from 'vitest'

// the GLB loader is replaced: no network, no file; everything else is the real three
const mode = { fail: false as boolean, scene: null as THREE.Group | null }
vi.mock('three/examples/jsm/loaders/GLTFLoader.js', () => ({
  GLTFLoader: class {
    async loadAsync() {
      if (mode.fail || !mode.scene) throw new Error('boom')
      return { scene: mode.scene, asset: { generator: 'test', extras: { author: 'someone', license: 'CC-BY' } } }
    }
  },
}))

import { makeUniforms } from './hologram'
import { getAsset } from './vehicleAssets'
import { applyAppearance, describeModel, disposeObject, loadVehicleGlb, normalizeModel, prepareVariants, TARGET_LENGTH } from './vehicleModel'

const named = (name: string) => Object.assign(new THREE.MeshStandardMaterial({ color: 0x884422 }), { name })

/** a stand-in "car" in file space: 4 long on -Z (the nose), 2 wide, 1.5 tall, with its own node scale like a cm-unit export */
function fakeCar(nose: 'z-' | 'x-' = 'z-') {
  const root = new THREE.Group()
  root.scale.setScalar(0.01) // the file is in centimetres
  const body = new THREE.Mesh(new THREE.BoxGeometry(nose === 'z-' ? 200 : 400, 150, nose === 'z-' ? 400 : 200), named('carpaint'))
  body.position.set(30, 75 + 12, -50) // not centred, not on the floor
  const tyre = new THREE.Mesh(new THREE.CylinderGeometry(30, 30, 20, 16), named('Material #43'))
  tyre.position.set(30, 30, -50)
  root.add(body, tyre)
  return root
}

describe('normalizeModel', () => {
  it('scales UNIFORMLY to 3.83 m, puts the nose on +X, centres the plan and rests on the floor', () => {
    const outer = normalizeModel(fakeCar('z-'), '-z')
    const box = new THREE.Box3().setFromObject(outer, true)
    const size = box.getSize(new THREE.Vector3())
    expect(size.x).toBeCloseTo(TARGET_LENGTH, 3)
    // proportions kept: the source box was 2 x 1.5 x 4 (+ the tyre below it): width / length = 0.5 and height / length = 0.375 or more
    expect(size.z / size.x).toBeCloseTo(2 / 4, 2)
    expect(box.min.y).toBeCloseTo(0, 3)
    expect((box.min.x + box.max.x) / 2).toBeCloseTo(0, 3)
    expect((box.min.z + box.max.z) / 2).toBeCloseTo(0, 3)
    // a single scale factor: the holder is never stretched per axis
    const holder = outer.children[0] as THREE.Group
    expect(holder.scale.x).toBe(holder.scale.y)
    expect(holder.scale.y).toBe(holder.scale.z)
  })

  it('handles each nose axis', () => {
    const outer = normalizeModel(fakeCar('x-'), '-x')
    const size = new THREE.Box3().setFromObject(outer, true).getSize(new THREE.Vector3())
    expect(size.x).toBeCloseTo(TARGET_LENGTH, 3)
    expect(size.z).toBeCloseTo(TARGET_LENGTH / 2, 2)
  })

  it('puts the nose at +X: a marker at the file nose ends up at the largest x', () => {
    const scene = fakeCar('z-')
    const marker = new THREE.Mesh(new THREE.SphereGeometry(5), named('detail'))
    marker.position.set(30, 90, -250 + 5) // at the -Z end (the nose of this file)
    scene.add(marker)
    const outer = normalizeModel(scene, '-z')
    outer.updateMatrixWorld(true)
    const p = new THREE.Vector3()
    marker.getWorldPosition(p)
    const box = new THREE.Box3().setFromObject(outer, true)
    expect(p.x).toBeGreaterThan(box.max.x - 0.2)
  })

  it('rejects an empty scene', () => {
    expect(() => normalizeModel(new THREE.Group(), '-z')).toThrow(/empty/)
  })
})

describe('looks are separate and reversible', () => {
  function build() {
    const outer = normalizeModel(fakeCar(), '-z')
    const tracked: Array<{ dispose(): void }> = []
    const fades: Array<[THREE.Material, number]> = []
    const hooks = { track: (d: { dispose(): void }) => void tracked.push(d), fade: (m: THREE.Material, b: number) => void fades.push([m, b]), edgeCache: new Map() }
    const variants = prepareVariants(outer, getAsset('model-c'), makeUniforms(), 1, hooks)
    return { outer, variants, tracked, fades, hooks }
  }

  it('gives each mesh a hologram, a grey and its untouched original, and amber lines only for the hologram', () => {
    const { outer, variants } = build()
    expect(variants).toHaveLength(2)
    const originals = variants.map((v) => v.original)
    expect(variants.map((v) => v.role).sort()).toEqual(['body', 'tyre'])
    applyAppearance(variants, 'hologram')
    for (const v of variants) {
      expect(v.mesh.material).toBe(v.holo)
      expect(v.mesh.material).not.toBe(v.original)
      expect(v.lines.every((l) => l.visible)).toBe(true)
    }
    applyAppearance(variants, 'grey')
    for (const v of variants) {
      expect(v.mesh.material).toBe(v.grey)
      expect(v.lines.every((l) => !l.visible)).toBe(true)
    }
    applyAppearance(variants, 'original')
    variants.forEach((v, i) => expect(v.mesh.material).toBe(originals[i]))
    expect(outer.children.length).toBe(1)
  })

  it('draws edge lines on creases only, and shares them between a car and its reflection', () => {
    const { outer, variants, hooks } = build()
    const box = variants.find((v) => v.role === 'body')!
    const lines = box.lines[0]!
    // a box has 12 real edges (24 vertices); never one line per triangle (a box has 12 triangles)
    expect(lines.geometry.getAttribute('position').count).toBeLessThanOrEqual(24)
    const twin = prepareVariants(outer.clone(true), getAsset('model-c'), makeUniforms(), 0.14, hooks)
    expect(twin.length).toBe(2)
    expect(hooks.edgeCache.size).toBe(2) // one cache entry per geometry, reused by the clone
  })

  it('registers the amber line materials for the scan-in fade and every created resource for disposal', () => {
    const { tracked, fades } = build()
    expect(fades.length).toBe(2)
    expect(tracked.length).toBeGreaterThanOrEqual(2 * 4)
  })
})

describe('describeModel and disposeObject', () => {
  it('counts triangles and meshes and reports the normalised size', () => {
    const outer = normalizeModel(fakeCar(), '-z')
    const s = describeModel(outer, 12)
    expect(s.meshes).toBe(2)
    expect(s.triangles).toBe(12 + 64) // box + 16-segment cylinder (16*4 triangles)
    expect(s.lengthM).toBeCloseTo(TARGET_LENGTH, 3)
    expect(s.loadMs).toBe(12)
  })

  it('disposes geometries, materials and textures of the loaded file', () => {
    const outer = normalizeModel(fakeCar(), '-z')
    const geo = vi.spyOn(THREE.BufferGeometry.prototype, 'dispose')
    const mat = vi.spyOn(THREE.Material.prototype, 'dispose')
    disposeObject(outer)
    expect(geo).toHaveBeenCalledTimes(2)
    expect(mat).toHaveBeenCalledTimes(2)
    geo.mockRestore()
    mat.mockRestore()
  })
})

describe('loadVehicleGlb', () => {
  beforeEach(() => {
    mode.fail = false
    mode.scene = fakeCar()
  })

  it('loads, normalises and keeps the file metadata (credits are not stripped)', async () => {
    const m = await loadVehicleGlb('/__local_vehicle/model-c.glb', 'model-c')
    expect(m.stats.meshes).toBe(2)
    expect(m.stats.lengthM).toBeCloseTo(TARGET_LENGTH, 3)
    expect(m.gltfAsset).toMatchObject({ generator: 'test', extras: { author: 'someone', license: 'CC-BY' } })
    m.dispose()
  })

  it('rejects when the file cannot be loaded (invalid or missing model)', async () => {
    mode.fail = true
    await expect(loadVehicleGlb('/__local_vehicle/nope.glb', 'model-c')).rejects.toThrow()
  })
})
