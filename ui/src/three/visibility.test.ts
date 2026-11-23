import * as THREE from 'three'
import { describe, expect, it } from 'vitest'
import { canClassify, decodeIds, isExterior, viewDirections } from './visibility'
import { exteriorEdges, splitByMask } from './vehicleModel'

describe('visibility pass helpers', () => {
  it('decodes triangle ids from RGBA pixels and counts them (0 is the background)', () => {
    const counts = new Uint32Array(300)
    // ids: 1, 1, 257 (= 1 + 1*256), 0 (background)
    decodeIds(new Uint8Array([1, 0, 0, 255, 1, 0, 0, 255, 1, 1, 0, 255, 0, 0, 0, 255]), counts)
    expect(counts[0]).toBe(2)
    expect(counts[256]).toBe(1)
    expect(counts.reduce((a, b) => a + b, 0)).toBe(3)
  })

  it('needs a real share of a triangle seen to call it exterior; a sliver through a gap is interior', () => {
    expect(isExterior(100, 100, 0.4)).toBe(1)
    expect(isExterior(30, 100, 0.4)).toBe(0)
    expect(isExterior(0, 0.2, 0.4)).toBe(0) // never seen
    expect(isExterior(1, 0.2, 0.4)).toBe(1) // a tiny triangle fully seen by one pixel
  })

  it('looks from all around and from above, never from below', () => {
    const dirs = viewDirections()
    expect(dirs.length).toBe(25)
    expect(dirs.every((d) => d.y > 0)).toBe(true)
    expect(Math.max(...dirs.map((d) => d.y))).toBeCloseTo(1, 2)
  })

  it('only a renderer that can read pixels back is asked to classify', () => {
    expect(canClassify({})).toBe(false)
    expect(canClassify({ readRenderTargetPixels() {}, setRenderTarget() {} })).toBe(true)
  })
})

/** a flat quad (2 triangles) plus a hanging quad folded 90 degrees from it (2 more), sharing an edge */
function foldedQuads() {
  const g = new THREE.BufferGeometry()
  g.setAttribute('position', new THREE.Float32BufferAttribute([0, 0, 0, 1, 0, 0, 1, 1, 0, 0, 1, 0, 0, 0, -1, 1, 0, -1], 3))
  g.setIndex([0, 1, 2, 0, 2, 3, 0, 4, 5, 0, 5, 1])
  return g
}

describe('splitByMask: exterior and interior share the original buffers', () => {
  it('puts exterior triangles first, in groups 0 and 1, and leaves the source index alone', () => {
    const g = foldedQuads()
    const before = Array.from(g.index!.array)
    const s = splitByMask(g, new Uint8Array([1, 0, 1, 0]), 30)
    expect(s.exteriorTriangles).toBe(2)
    expect(s.interiorTriangles).toBe(2)
    expect(s.geometry.groups).toEqual([
      { start: 0, count: 6, materialIndex: 0 },
      { start: 6, count: 6, materialIndex: 1 },
    ])
    expect(Array.from(g.index!.array)).toEqual(before) // the file's own index is untouched
    expect(s.geometry.getAttribute('position')).toBe(g.getAttribute('position')) // shared, not copied
  })

  it('one group when everything is exterior, and rejects a mask of the wrong size', () => {
    const g = foldedQuads()
    expect(splitByMask(g, new Uint8Array([1, 1, 1, 1]), 30).geometry.groups).toHaveLength(1)
    expect(() => splitByMask(g, new Uint8Array([1]), 30)).toThrow(/mask/)
  })
})

describe('exteriorEdges: creases of the visible part, no artificial borders from the mask', () => {
  it('draws the fold between two quads when one of them is exterior', () => {
    const e = exteriorEdges(foldedQuads(), new Uint8Array([1, 1, 0, 0]), 30)
    expect(e.getAttribute('position').count).toBeGreaterThan(0)
  })

  it('draws nothing for a fully interior part', () => {
    const e = exteriorEdges(foldedQuads(), new Uint8Array([0, 0, 0, 0]), 30)
    expect(e.getAttribute('position').count).toBe(0)
  })

  it('a flat, closed-looking patch masked away from its neighbour adds no line along the cut', () => {
    // two coplanar triangles: the shared edge is not a crease, and cutting one away must not invent a boundary line there
    const g = new THREE.BufferGeometry()
    g.setAttribute('position', new THREE.Float32BufferAttribute([0, 0, 0, 1, 0, 0, 1, 1, 0, 0, 1, 0], 3))
    g.setIndex([0, 1, 2, 0, 2, 3])
    const e = exteriorEdges(g, new Uint8Array([1, 0]), 30)
    const segments = e.getAttribute('position').count / 2
    expect(segments).toBe(2) // the visible triangle's 2 true open borders; the shared coplanar diagonal (the cut) is not drawn
  })
})
