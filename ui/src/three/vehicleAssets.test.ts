import { describe, expect, it } from 'vitest'
import { getAsset, isAssetId, roleKey, roleOf } from './vehicleAssets'
import { LOCAL_ASSETS } from './vehicleAssets.local'

describe('vehicle asset registry', () => {
  it('maps material names to part roles, whatever the exporter did to the punctuation', () => {
    const c = getAsset('model-c')
    expect(roleOf(c, 'carpaint')).toBe('body')
    expect(roleOf(c, 'black')).toBe('trim')
    expect(roleOf(c, 'window_glass')).toBe('glass')
    expect(roleOf(c, 'clearglass')).toBe('glass')
    expect(roleOf(c, 'Material #43')).toBe('tyre')
    expect(roleOf(c, 'Material_43')).toBe('tyre')
    expect(roleOf(c, 'Material #56')).toBe('rim')
    expect(roleOf(c, 'Material #28')).toBe('detail')
    expect(roleOf(c, undefined)).toBe('detail')
    const a = getAsset('model-a')
    expect(roleOf(a, 'Material.003')).toBe('tyre')
    expect(roleOf(a, 'Material.005')).toBe('glass')
    expect(roleKey('Material #043')).toBe('material_43')
  })

  it('knows its ids and falls back to the procedural car for anything else', () => {
    expect(isAssetId('model-c')).toBe(true)
    expect(isAssetId('placeholder')).toBe(true)
    expect(isAssetId('../etc/passwd')).toBe(false)
    expect(isAssetId(undefined)).toBe(false)
    expect(getAsset('placeholder').localOnly).toBe(false)
  })

  it('marks the local preview assets as local-only and the game-derived one as rights-unconfirmed', () => {
    expect(LOCAL_ASSETS['model-c'].localOnly).toBe(true)
    expect(LOCAL_ASSETS['model-c'].rights).toMatch(/NÃO CONFIRMADOS/)
    expect(LOCAL_ASSETS['model-c'].credit).toMatch(/Gran Turismo 6/)
    expect(LOCAL_ASSETS['model-a'].rights).toMatch(/CC BY/)
  })

  it('stores no file, path or URL of any asset in the source tree', () => {
    const text = JSON.stringify(LOCAL_ASSETS) + JSON.stringify(getAsset('placeholder'))
    expect(text).not.toMatch(/\.glb|\.fbx|[A-Za-z]:[\\/]|https?:|\/__local/i)
  })
})
