/**
 * DEVELOPMENT-ONLY registry of the LOCAL PREVIEW vehicle assets (models A and C). This module is imported only behind
 * `import.meta.env.DEV`, so none of it (names, credits, the local route) reaches a production build. It holds metadata only:
 * no file, no path of any asset. The files are named by the developer's git-ignored config (ui/.local/vehicle-models.json) and
 * served by the dev server alone (vite.local-assets.mjs).
 */
import type { VehicleAsset, VehicleAssetId } from './vehicleAssets'

export const LOCAL_ASSETS: Record<'model-a' | 'model-c', VehicleAsset> = {
  'model-a': {
    id: 'model-a',
    label: 'A · 2006 Honda Fit GD3',
    localOnly: true,
    frontAxis: '-x',
    roles: { material_001: 'body', material_002: 'body', material_003: 'tyre', material_004: 'rim', material_005: 'glass' },
    credit: '"2006 Honda Fit GD3" por kusuma844, Sketchfab, CC BY 4.0.',
    rights: 'CC BY 4.0 (atribuição). Honda é marca de terceiros. Prévia local: o arquivo não está no repositório.',
  },
  'model-c': {
    id: 'model-c',
    label: 'C · Honda Jazz 1.4 DSi (GT6)',
    localOnly: true,
    frontAxis: '-z',
    roles: {
      carpaint: 'body',
      black: 'trim',
      clearglass: 'glass',
      window_glass: 'glass',
      material_43: 'tyre',
      material_56: 'rim',
    },
    credit: '"Honda Jazz 1.4 DSi SE Sport \'01" por Asadawut.Kaewma, Sketchfab; segundo o autor, "Model From Gran Turismo 6".',
    rights: 'DIREITOS NÃO CONFIRMADOS (ativo extraído de jogo). Somente prévia local; não redistribuir; não versionar.',
  },
}

/** the local, dev-server-only URL of a preview asset */
export const localAssetUrl = (id: VehicleAssetId) => `/__local_vehicle/${id}.glb`
