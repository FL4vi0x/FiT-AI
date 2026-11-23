import react from '@vitejs/plugin-react'
import { defineConfig, type Plugin } from 'vitest/config'
import localVehicleAssets from './vite.local-assets.mjs'

// The UI talks to the Fit AI Core through a same-origin proxy: the browser only ever sees this server, so the Core
// needs no CORS headers (it emits none, by design). The Core refuses non-loopback targets, and so does this proxy.
declare const process: { env: Record<string, string | undefined> } // Node global; no @types/node needed for one variable
const CORE = process.env.FIT_AI_CORE_URL ?? 'http://127.0.0.1:8000'
const host = new URL(CORE).hostname
if (!['127.0.0.1', 'localhost', '[::1]', '::1'].includes(host)) {
  throw new Error(`FIT_AI_CORE_URL must point to a loopback address, got ${CORE}`)
}

// Strict policy for the production build only (the dev server needs inline HMR scripts and a websocket).
const CSP = [
  "default-src 'self'",
  "script-src 'self'",
  "style-src 'self' 'unsafe-inline'", // framer-motion and SVG animation write inline styles
  "img-src 'self' data:",
  "font-src 'self'",
  "connect-src 'self'",
  "object-src 'none'",
  "base-uri 'none'",
  "form-action 'none'",
].join('; ')

function cspForBuild(): Plugin {
  return {
    name: 'fit-ai-csp',
    apply: 'build',
    transformIndexHtml: (html) =>
      html.replace('<!--csp-->', `<meta http-equiv="Content-Security-Policy" content="${CSP}" />`),
  }
}

const proxy = {
  '/api': { target: CORE, changeOrigin: true }, // changeOrigin: the Core's Host guard only serves local names
  '/health': { target: CORE, changeOrigin: true },
}

export default defineConfig({
  // localVehicleAssets: dev server only, loopback only, reads a git-ignored config; never part of the build or of `vite preview`
  plugins: [react(), cspForBuild(), localVehicleAssets({ configPath: process.env.FIT_LOCAL_VEHICLE_CONFIG ?? '.local/vehicle-models.json' })],
  server: { host: '127.0.0.1', port: 5173, strictPort: true, proxy },
  preview: { host: '127.0.0.1', port: 4173, strictPort: true, proxy },
  build: {
    sourcemap: false,
    target: 'es2022',
    rollupOptions: {
      output: {
        // three.js is loaded lazily (only the active screen pulls it in) and rarely changes, while the app's own 3D code changes often:
        // its own chunk gets its own cache entry. Its size is inherent to the renderer, so the warning limit is set just above it.
        // the loader in three/examples stays its own lazy chunk: it is only fetched when a model file is actually configured
        manualChunks: (id) => (id.includes('/node_modules/three/') && !id.includes('/node_modules/three/examples/') ? 'three' : undefined),
      },
    },
    chunkSizeWarningLimit: 560,
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    css: false,
    include: ['src/**/*.test.{ts,tsx}'],
  },
})
