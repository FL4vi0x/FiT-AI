import { afterEach, describe, expect, it, vi } from 'vitest'
import { parseDevPreview, wantsDemo } from './devPreview'

describe('development preview knobs', () => {
  it('reads vehicle, look and yaw from the hash', () => {
    expect(parseDevPreview('#/active?vehicle=model-c&look=grey&yaw=-35.5')).toEqual({ asset: 'model-c', appearance: 'grey', yawDeg: -35.5, camera: null, view: null })
    expect(parseDevPreview('#/active?vehicle=model-a&look=original')).toEqual({ asset: 'model-a', appearance: 'original', yawDeg: null, camera: null, view: null })
  })

  it('defaults to the procedural car and the hologram', () => {
    expect(parseDevPreview('#/active')).toEqual({ asset: 'placeholder', appearance: 'hologram', yawDeg: null, camera: null, view: null })
    expect(parseDevPreview('')).toEqual({ asset: 'placeholder', appearance: 'hologram', yawDeg: null, camera: null, view: null })
  })

  it('ignores unknown ids, looks and non-numeric yaw (nothing is ever turned into a URL or a path)', () => {
    expect(parseDevPreview('#/active?vehicle=../../etc&look=wireframe&yaw=abc')).toEqual({ asset: 'placeholder', appearance: 'hologram', yawDeg: null, camera: null, view: null })
  })

  it('reads a named camera and view, and ignores odd ones', () => {
    const p = parseDevPreview('#/active?cam=high&view=front34')
    expect(p.camera).toBe('high')
    expect(p.view).toBe('front34')
    const bad = parseDevPreview('#/active?cam=../x&view=<script>')
    expect(bad.camera).toBeNull()
    expect(bad.view).toBeNull()
  })

  it('wantsDemo only with the flag', () => {
    expect(wantsDemo('#/active?demo')).toBe(true)
    expect(wantsDemo('#/active?vehicle=model-c&demo')).toBe(true)
    expect(wantsDemo('#/active?vehicle=model-c')).toBe(false)
  })
})

describe('the machine-local default vehicle', () => {
  afterEach(() => vi.unstubAllEnvs())

  it('is used when the hash names no vehicle, and never overrides an explicit one', () => {
    vi.stubEnv('VITE_FIT_DEFAULT_VEHICLE', 'model-c')
    expect(parseDevPreview('#/active').asset).toBe('model-c')
    expect(parseDevPreview('').asset).toBe('model-c')
    expect(parseDevPreview('#/active?vehicle=placeholder').asset).toBe('placeholder')
    expect(parseDevPreview('#/active?vehicle=model-a').asset).toBe('model-a')
  })

  it('ignores anything that is not a known id', () => {
    vi.stubEnv('VITE_FIT_DEFAULT_VEHICLE', '../../etc/passwd')
    expect(parseDevPreview('#/active').asset).toBe('placeholder')
  })
})
