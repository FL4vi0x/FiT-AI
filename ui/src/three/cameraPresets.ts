/**
 * Camera and view constants of the vehicle stage (no three.js import: the dev switches read them too).
 * The car's nose points +X; `yaw` is the rotation of the car about the vertical axis: PI turns the nose to the viewer's left (a side view),
 * PI + a (a > 0) brings the nose towards the camera.
 */
export interface CameraPreset {
  fov: number
  position: [number, number, number]
  target: [number, number, number]
}

/** the camera that was used until the refinement: a long lens from far away, which flattens the nose */
export const CAMERA_LEGACY: CameraPreset = { fov: 22, position: [0, 2.3, 8.4], target: [0, 0.7, 0] }

/** the refined camera: a moderate lens, closer and a little higher, so the front has depth and the antenna clears the voice core */
export const CAMERA_REFINED: CameraPreset = { fov: 30, position: [0, 2.7, 6.9], target: [0, 1.0, 0] }

export const CAMERA_PRESETS: Record<string, CameraPreset> = {
  legacy: CAMERA_LEGACY,
  refined: CAMERA_REFINED,
  high: { fov: 30, position: [0, 3.3, 7.0], target: [0, 0.95, 0] },
  wide: { fov: 38, position: [0, 2.5, 5.6], target: [0, 0.95, 0] },
}

/** the car is seen from the front-left, three quarters, about 38 degrees off its nose axis (the legacy view was 54 degrees: too lateral) */
export const BASE_YAW = Math.PI + 0.9
/** ambient rotation: a slow swing of +-11.5 degrees with a 50 s period, so the three-quarter view is never lost */
export const SWING = { amplitude: 0.2, periodSeconds: 50 }

/** named views (development captures): the yaw of the car, absolute */
export const VIEW_YAW: Record<string, number> = {
  front34: BASE_YAW,
  side: Math.PI,
  front: Math.PI + 1.25, // about 20 degrees off the nose axis: "almost front"
  rear34: Math.PI - 0.9,
}
