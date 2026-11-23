import { useEffect, useRef } from 'react'
import { VEHICLE_REVEAL_AT } from '../../motion/activeTimeline'
import { VehicleScene, type SceneEvent } from '../../three/VehicleScene'
import { PLACEHOLDER_ID } from '../../three/fitPlaceholder'
import { type Appearance, type VehicleAssetId } from '../../three/vehicleAssets'
import { localAssetUrl } from '../../three/vehicleAssets.local'
import type { ModelStats } from '../../three/vehicleModel'
import styles from '../../screens/ActiveScreen/ActiveScreen.module.css'

export type VehicleStatus = 'ready' | 'unsupported' | 'lost'

export interface VehicleModelInfo {
  asset: VehicleAssetId
  state: 'loading' | 'loaded' | 'missing'
  stats?: ModelStats | null
}

/** Optional licensed model for a production build (none today); development previews use localAssetUrl() instead. */
const MODEL_URL: string | undefined = import.meta.env.VITE_FIT_MODEL_URL || undefined

interface Props {
  reduced: boolean
  onStatus: (s: VehicleStatus) => void
  /** development only: which preview asset to load (production always shows the procedural car) */
  asset?: VehicleAssetId
  appearance?: Appearance
  /** bump to go back to the three-quarter view (development) */
  resetToken?: number
  devControls?: boolean
  initialYawDeg?: number | null
  /** development: named camera and view (cameraPresets.ts) */
  cameraPreset?: string | null
  view?: string | null
  onModel?: (i: VehicleModelInfo) => void
}

/**
 * The canvas around VehicleScene (loaded lazily, so the 3D code is a separate chunk that only the active screen pulls in).
 * Lifecycle: created on mount, paused while the tab is hidden, resized with its box, fully disposed on unmount. Remount (key)
 * to change the asset: the old scene releases everything before the new one is built.
 */
export default function HolographicVehicle({ reduced, onStatus, asset = 'placeholder', appearance = 'hologram', resetToken = 0, devControls = false, initialYawDeg = null, cameraPreset = null, view = null, onModel }: Props) {
  const host = useRef<HTMLDivElement>(null)
  const sceneRef = useRef<VehicleScene | null>(null)
  const status = useRef(onStatus)
  status.current = onStatus
  const modelCb = useRef(onModel)
  modelCb.current = onModel
  const look = useRef(appearance)
  look.current = appearance

  useEffect(() => {
    const el = host.current
    if (!el) return
    // A fresh canvas per mount: dispose() force-loses the WebGL context, and React StrictMode (dev) mounts, unmounts and mounts
    // again on the same DOM node, which would otherwise hand the second mount a dead context.
    const canvas = document.createElement('canvas')
    canvas.className = styles.vehicleCanvas ?? ''
    canvas.dataset.testid = 'vehicle-canvas'
    canvas.dataset.model = PLACEHOLDER_ID
    canvas.setAttribute('role', 'img')
    canvas.setAttribute('aria-label', 'Honda Fit holográfico (modelo provisório)')
    el.appendChild(canvas)
    const dev = import.meta.env.DEV
    const localAsset = dev && asset !== 'placeholder'
    let scene: VehicleScene
    try {
      scene = new VehicleScene(canvas, {
        reduced,
        modelUrl: import.meta.env.DEV && localAsset ? localAssetUrl(asset) : MODEL_URL,
        assetId: localAsset ? asset : 'placeholder',
        appearance: look.current,
        devControls: dev && devControls,
        initialYawOffset: dev && initialYawDeg !== null ? (initialYawDeg * Math.PI) / 180 : undefined,
        camera: dev ? (cameraPreset ?? undefined) : undefined,
        view: dev ? (view ?? undefined) : undefined,
        publishStats: dev,
        onEvent: (e: SceneEvent) => {
          if (e === 'lost') status.current('lost')
          if (e === 'ready' || e === 'restored') status.current('ready')
          if (e === 'model-loading') modelCb.current?.({ asset, state: 'loading' })
          if (e === 'model-loaded') modelCb.current?.({ asset, state: 'loaded', stats: sceneRef.current?.stats().model ?? null })
          if (e === 'model-missing') modelCb.current?.({ asset, state: 'missing' })
        },
      })
    } catch {
      canvas.remove()
      status.current('unsupported')
      return
    }
    sceneRef.current = scene
    scene.start()
    const reveal = setTimeout(() => scene.setReveal(1), reduced ? 0 : VEHICLE_REVEAL_AT)
    const ro = new ResizeObserver(() => scene.resize())
    ro.observe(canvas)
    const onVisibility = () => (document.hidden ? scene.stop() : scene.start())
    document.addEventListener('visibilitychange', onVisibility)
    return () => {
      clearTimeout(reveal)
      ro.disconnect()
      document.removeEventListener('visibilitychange', onVisibility)
      sceneRef.current = null
      scene.dispose()
      canvas.remove()
    }
    // asset / devControls / initialYawDeg are fixed for a mount: VehicleStage remounts (key) to change the asset
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reduced, asset])

  useEffect(() => {
    sceneRef.current?.setAppearance(appearance)
  }, [appearance])

  useEffect(() => {
    if (resetToken > 0) sceneRef.current?.resetView()
  }, [resetToken])

  return <div ref={host} className={styles.vehicleHost} />
}
