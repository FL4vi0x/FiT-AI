import * as THREE from 'three'

export const AMBER = new THREE.Color('#ff8500')
export const AMBER_HOT = new THREE.Color('#ffaa38')
/** the body's shadow tone from the P8.2 brief */
export const BODY_SHADOW = '#130a04'

/** uniforms shared by every hologram material of one car (time and the scan-in reveal move together) */
export interface HoloUniforms {
  uTime: { value: number }
  /** 0..1 reveal: the body is scanned in from the floor up while it fades in */
  uReveal: { value: number }
  uOpacity: { value: number }
  uScan: { value: number }
  /** depth cue: surfaces between uNear and uFar (view-space distance, metres) fade towards 30%: the far side of the car recedes */
  uNear: { value: number }
  uFar: { value: number }
}

export function makeUniforms(): HoloUniforms {
  return { uTime: { value: 0 }, uReveal: { value: 0 }, uOpacity: { value: 1 }, uScan: { value: 1 }, uNear: { value: 0 }, uFar: { value: 1000 } }
}

/** how one kind of part is painted: its base tone, how strong the amber rim light is and how opaque the glass is */
export interface HoloLook {
  base: string
  rim: number
  alpha: number
  /** how much the grazing-angle rim also raises the opacity (0.5 by default; interior parts use almost none) */
  fresAlpha?: number
  /** sharpness of the rim: a high power keeps flat surfaces dark and lights only the silhouette (1.5 by default) */
  fresPower?: number
  /** use the file's smoothed vertex normals for the rim instead of flat per-face normals (hides the facets of large low-poly panels) */
  smooth?: boolean
}

export const DEFAULT_LOOK: HoloLook = { base: BODY_SHADOW, rim: 1.0, alpha: 0.3 }

/**
 * Hologram surface: nearly transparent dark glass with a fresnel rim in amber and a faint scan band. One cheap ShaderMaterial,
 * no post-processing, no texture. `uReveal` clips it from the floor up, in WORLD height (so it works for any model, whatever
 * the units or the node transforms of its file); the mirrored floor reflection uses |y|.
 */
export function makeHoloMaterial(shared: HoloUniforms, look: HoloLook = DEFAULT_LOOK): THREE.ShaderMaterial {
  return new THREE.ShaderMaterial({
    uniforms: {
      uTime: shared.uTime,
      uReveal: shared.uReveal,
      uOpacity: shared.uOpacity,
      uScan: shared.uScan,
      uNear: shared.uNear,
      uFar: shared.uFar,
      uBase: { value: new THREE.Color(look.base) },
      uRimK: { value: look.rim },
      uAlphaK: { value: look.alpha },
      uFresA: { value: look.fresAlpha ?? 0.5 },
      uFresP: { value: look.fresPower ?? 1.5 },
    } as Record<string, THREE.IUniform>,
    defines: look.smooth ? { SMOOTH_N: '' } : {},
    transparent: true,
    depthWrite: false,
    side: THREE.DoubleSide,
    blending: THREE.NormalBlending,
    vertexShader: /* glsl */ `
      varying vec3 vP; varying float vY; varying vec3 vN;
      void main(){
        vec4 wp = modelMatrix * vec4(position,1.0);
        vec4 mv = viewMatrix * wp;
#ifdef SMOOTH_N
        vN = normalize(normalMatrix * normal);
#else
        vN = vec3(0.0, 0.0, 1.0);
#endif
        vP = mv.xyz;
        vY = abs(wp.y);
        gl_Position = projectionMatrix * mv;
      }`,
    fragmentShader: /* glsl */ `
      uniform float uTime; uniform float uReveal; uniform float uOpacity; uniform float uScan; uniform float uNear; uniform float uFar;
      uniform vec3 uBase; uniform float uRimK; uniform float uAlphaK; uniform float uFresA; uniform float uFresP;
      varying vec3 vP; varying float vY; varying vec3 vN;
      void main(){
        float h = uReveal * 2.1;
        if (vY > h) discard;
        float edge = smoothstep(h - 0.18, h, vY) * step(uReveal, 0.999);
        // face normal from screen-space derivatives: stable on lofted or noisy meshes
#ifdef SMOOTH_N
        vec3 n = normalize(vN);
#else
        vec3 n = normalize(cross(dFdx(vP), dFdy(vP)));
#endif
        float fres = pow(1.0 - abs(dot(n, normalize(-vP))), uFresP);
        float band = 0.5 + 0.5 * sin(vY * 38.0 - uTime * 0.9);
        vec3 amber = vec3(1.0, 0.52, 0.04);
        vec3 col = uBase + amber * (fres * uRimK + band * 0.05 * uScan + edge * 0.9);
        // depth cue: the part of the car farthest from the camera recedes, so the near side reads first
        float depthFade = 1.0 - 0.7 * smoothstep(uNear, uFar, -vP.z);
        float a = (uAlphaK + fres * uFresA + edge * 0.5) * uOpacity * depthFade;
        gl_FragColor = vec4(col * depthFade, a);
      }`,
  })
}

/** the original single-look body material (kept: the procedural placeholder and the tests use it) */
export function makeHoloBodyMaterial(u: HoloUniforms): THREE.ShaderMaterial {
  return makeHoloMaterial(u, DEFAULT_LOOK)
}

export function makeLineMaterial(opacity: number, hot = false): THREE.LineBasicMaterial {
  return new THREE.LineBasicMaterial({ color: hot ? AMBER_HOT : AMBER, transparent: true, opacity, depthWrite: false })
}
