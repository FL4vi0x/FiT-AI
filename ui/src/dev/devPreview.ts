import { isAssetId, type Appearance, type VehicleAssetId } from '../three/vehicleAssets'

export const wantsDemo = (hash: string) => /[?&]demo\b/.test(hash)

export interface DevPreview {
  asset: VehicleAssetId
  appearance: Appearance
  /** manual yaw offset from the three-quarter view, in degrees (null: ambient rotation as usual) */
  yawDeg: number | null
  /** a named camera (cameraPresets.ts) and a named view (front34, side, front, rear34) */
  camera: string | null
  view: string | null
}

/**
 * Development-only knobs read from the hash: `#/active?vehicle=model-c&look=grey&yaw=-35`. In a production build `devPreview()`
 * returns null, so none of this exists: the car is the procedural one and nothing asks for a local asset.
 */
/**
 * The car this machine shows by default: `VITE_FIT_DEFAULT_VEHICLE` from the git-ignored `ui/.env.development.local`. Vite loads that
 * file only for the dev server, so builds and tests never see it and the default stays the procedural car.
 */
function localDefault(): VehicleAssetId {
  const d = import.meta.env.VITE_FIT_DEFAULT_VEHICLE
  return isAssetId(d) ? d : 'placeholder'
}

export function parseDevPreview(hash: string): DevPreview {
  const q = new URLSearchParams(hash.includes('?') ? hash.slice(hash.indexOf('?') + 1) : '')
  const v = q.get('vehicle')
  const look = q.get('look')
  const yaw = q.get('yaw')
  return {
    // an explicit `vehicle=` wins (so `vehicle=placeholder` always gives the procedural car); otherwise the machine's own local default
    asset: isAssetId(v) ? v : localDefault(),
    appearance: look === 'grey' || look === 'original' || look === 'split' ? look : 'hologram',
    yawDeg: yaw !== null && Number.isFinite(Number(yaw)) ? Number(yaw) : null,
    camera: /^[a-z]{1,12}$/.test(q.get('cam') ?? '') ? q.get('cam') : null,
    view: /^[a-z0-9]{1,12}$/.test(q.get('view') ?? '') ? q.get('view') : null,
  }
}

export function devPreview(): DevPreview | null {
  return import.meta.env.DEV ? parseDevPreview(window.location.hash) : null
}
