import { LOCAL_ASSETS } from '../../three/vehicleAssets.local'
import { getAsset, type Appearance, type VehicleAssetId } from '../../three/vehicleAssets'
import type { VehicleModelInfo } from './HolographicVehicle'
import styles from '../../screens/ActiveScreen/ActiveScreen.module.css'

const APPEARANCES: Appearance[] = ['hologram', 'grey', 'original']
const IDS: VehicleAssetId[] = ['placeholder', ...(Object.keys(LOCAL_ASSETS) as VehicleAssetId[])]

export function devBadgeText(asset: VehicleAssetId, model: VehicleModelInfo | null): string {
  const info = getAsset(asset)
  if (asset === 'placeholder') return 'MODELO PROVISÓRIO · não é o Honda Fit GD'
  if (model?.state === 'loaded') return `PRÉVIA LOCAL · ${info.label} · direitos ${asset === 'model-c' ? 'NÃO confirmados' : 'CC BY'} · não redistribuir`
  if (model?.state === 'missing') return `MODELO LOCAL AUSENTE (${info.label}) · usando o provisório`
  return `CARREGANDO PRÉVIA LOCAL · ${info.label}`
}

interface Props {
  asset: VehicleAssetId
  appearance: Appearance
  model: VehicleModelInfo | null
  /** the switcher panel appears only with `?demo`; the labelled badge always shows in development */
  panel: boolean
  onAsset: (id: VehicleAssetId) => void
  onAppearance: (a: Appearance) => void
  onReset: () => void
}

/** DEVELOPMENT ONLY (lazy-loaded behind import.meta.env.DEV, so absent from a production build): the preview badge and switcher. */
export default function DevVehiclePanel({ asset, appearance, model, panel, onAsset, onAppearance, onReset }: Props) {
  const info = getAsset(asset)
  const label = (id: VehicleAssetId) => (id === 'placeholder' ? getAsset('placeholder').label : LOCAL_ASSETS[id as 'model-a' | 'model-c'].label)
  return (
    <>
      <p className={styles.devBadge} data-testid="dev-badge" title={info.credit}>
        {devBadgeText(asset, model)}
      </p>
      {panel && (
        <div className={styles.devVehiclePanel} role="group" aria-label="Prévia do veículo (somente desenvolvimento)" data-testid="dev-vehicle-panel">
          <div>
            {IDS.map((id) => (
              <button key={id} type="button" aria-pressed={asset === id} onClick={() => onAsset(id)} data-testid={`dev-asset-${id}`}>
                {label(id)}
              </button>
            ))}
          </div>
          <div>
            {APPEARANCES.map((a) => (
              <button key={a} type="button" aria-pressed={appearance === a} onClick={() => onAppearance(a)} data-testid={`dev-look-${a}`}>
                {a === 'hologram' ? 'holograma' : a === 'grey' ? 'cinza' : 'original'}
              </button>
            ))}
            <button type="button" onClick={onReset} data-testid="dev-reset-view">
              restaurar câmera
            </button>
          </div>
          <small>{info.credit}</small>
        </div>
      )}
    </>
  )
}
