import { lazy, Suspense, useState } from 'react'
import { devPreview, wantsDemo } from '../../dev/devPreview'
import type { Appearance, VehicleAssetId } from '../../three/vehicleAssets'
import type { VehicleModelInfo, VehicleStatus } from './HolographicVehicle'
import styles from '../../screens/ActiveScreen/ActiveScreen.module.css'

// the whole Three.js module (renderer, scene, shaders) loads only here, on demand
const HolographicVehicle = lazy(() => import('./HolographicVehicle'))
// development only: the preview badge and switcher. In a production build this is `null` and the module is not emitted.
const DevVehiclePanel = import.meta.env.DEV ? lazy(() => import('./DevVehiclePanel')) : null

/**
 * The 3D vehicle with its loading and failure states. The HUD around it never depends on WebGL.
 * In development, `#/active?vehicle=model-c&look=grey&yaw=-35` (and, with `?demo`, a small panel) selects a local preview asset,
 * its look and the view. None of this exists in a production build: the car is the procedural one and nothing is requested.
 */
export function VehicleStage({ reduced }: { reduced: boolean }) {
  const dev = import.meta.env.DEV
  const initial = dev ? devPreview() : null
  const [status, setStatus] = useState<VehicleStatus>('ready')
  const [asset, setAsset] = useState<VehicleAssetId>(initial?.asset ?? 'placeholder')
  const [appearance, setAppearance] = useState<Appearance>(initial?.appearance ?? 'hologram')
  const [resetToken, setResetToken] = useState(0)
  const [model, setModel] = useState<VehicleModelInfo | null>(null)

  return (
    <div className={styles.vehicle} data-testid="vehicle-stage" data-status={status} data-asset={asset}>
      {status !== 'unsupported' && (
        <Suspense fallback={null}>
          <HolographicVehicle
            key={asset}
            reduced={reduced}
            onStatus={setStatus}
            asset={asset}
            appearance={appearance}
            resetToken={resetToken}
            devControls={dev}
            initialYawDeg={initial?.yawDeg ?? null}
            cameraPreset={initial?.camera ?? null}
            view={initial?.view ?? null}
            onModel={setModel}
          />
        </Suspense>
      )}
      {status !== 'ready' && (
        <p className={styles.vehicleNotice} role="status" data-testid="vehicle-notice">
          {status === 'lost' ? 'A visualização 3D foi interrompida pelo navegador. Ela volta sozinha quando o gráfico for restaurado.' : 'A visualização 3D do veículo não está disponível neste dispositivo.'}
        </p>
      )}
      {DevVehiclePanel && (
        <Suspense fallback={null}>
          <DevVehiclePanel
            asset={asset}
            appearance={appearance}
            model={model}
            panel={wantsDemo(window.location.hash)}
            onAsset={(id) => {
              setModel(null)
              setAsset(id)
            }}
            onAppearance={setAppearance}
            onReset={() => setResetToken((n) => n + 1)}
          />
        </Suspense>
      )}
    </div>
  )
}
