/**
 * Which 3D car to show. METADATA ONLY: no file, no path and no URL of any asset is stored in the source tree.
 * `model-a` and `model-c` are LOCAL PREVIEW assets: their registry lives in vehicleAssets.local.ts, which is imported only in
 * development (it never reaches a production build); the files exist only if the developer's git-ignored config names them, they
 * are served by the dev server alone, and nothing outside development ever asks for them.
 */
import { LOCAL_ASSETS } from './vehicleAssets.local'

export type VehicleAssetId = 'placeholder' | 'model-a' | 'model-c'

/** how the car is painted: the amber hologram, a neutral grey (to judge the shape), the file's own original materials, or `split`: a development diagnostic that paints exterior triangles green and interior ones red */
export type Appearance = 'hologram' | 'grey' | 'original' | 'split'

/** what a part is, to paint it: the body panels, dark trim, glass, tyres, wheel centres or small details (lamps, plate...) */
export type PartRole = 'body' | 'trim' | 'glass' | 'tyre' | 'rim' | 'detail'

/** the axis of the FILE (glTF space: +Y up) that the car's nose points along */
export type FrontAxis = '+x' | '-x' | '+z' | '-z'

export interface VehicleAsset {
  id: VehicleAssetId
  label: string
  /** development only: never offered, never requested, in a production build */
  localOnly: boolean
  frontAxis: FrontAxis
  /** role by material name (see roleKey); anything not listed is a `detail` */
  roles: Record<string, PartRole>
  credit: string
  rights: string
}

/** the procedural car, and the neutral defaults for any other GLB (e.g. a future licensed model named by VITE_FIT_MODEL_URL) */
const PLACEHOLDER: VehicleAsset = {
  id: 'placeholder',
  label: 'Provisório (procedural)',
  localOnly: false,
  frontAxis: '+x',
  roles: {},
  credit: 'Geometria procedural do projeto (não é um Honda Fit GD).',
  rights: 'Obra do projeto.',
}

/** the asset description for `id`; the local preview entries exist in development only */
export function getAsset(id: VehicleAssetId): VehicleAsset {
  const local = import.meta.env.DEV ? (LOCAL_ASSETS as Record<string, VehicleAsset>)[id] : undefined
  return local ?? PLACEHOLDER
}

export function isAssetId(x: unknown): x is VehicleAssetId {
  return x === 'placeholder' || x === 'model-a' || x === 'model-c'
}

/** material names differ in punctuation between exporters ("Material #43", "Material_43", "Material.043"): compare on a normalised key */
export function roleKey(materialName: string): string {
  return materialName.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/_0+(?=\d)/g, '_').replace(/^_|_$/g, '')
}

export function roleOf(asset: VehicleAsset, materialName: string | undefined): PartRole {
  if (!materialName) return 'detail'
  const key = roleKey(materialName)
  const direct = asset.roles[key]
  if (direct) return direct
  // "material_001" in the table also matches "material_1" produced by the normaliser
  for (const [k, role] of Object.entries(asset.roles)) if (roleKey(k) === key) return role
  return 'detail'
}
