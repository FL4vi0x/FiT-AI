// DEV-ONLY, LOCAL-ONLY server for rights-restricted vehicle assets (P8.2 model preview).
//
// The files are NOT in public/, NOT in src/ and NOT tracked: their absolute paths live in ui/.local/vehicle-models.json (git-ignored).
// This middleware exists only in `vite` (dev server): `apply: 'serve'` keeps it out of `vite build` and `vite preview`, so no build
// output ever contains or exposes them. It answers only loopback sockets with a loopback Host header (no LAN, no DNS rebinding),
// only for ids named in the local config, never from a path taken from the URL, never cached.
// Serving on localhost is NOT a legal licence to use the asset: see docs/poc-08-02-model-c-preview.md.
import fs from 'node:fs'
import path from 'node:path'

export const LOCAL_VEHICLE_PREFIX = '/__local_vehicle/'
const LOOPBACK = new Set(['127.0.0.1', '::1', '::ffff:127.0.0.1'])
const HOST_OK = /^(127\.0\.0\.1|localhost|\[::1\])(:\d{1,5})?$/i

function deny(res, code, why) {
  res.statusCode = code
  res.setHeader('Content-Type', 'text/plain; charset=utf-8')
  res.setHeader('Cache-Control', 'no-store')
  res.end(why)
}

export function createHandler(readConfig) {
  return function localVehicleHandler(req, res, next) {
    const url = (req.url || '').split('?')[0]
    if (!url.startsWith(LOCAL_VEHICLE_PREFIX)) return next()
    if (req.method !== 'GET' && req.method !== 'HEAD') return deny(res, 405, 'method not allowed')
    if (!LOOPBACK.has(req.socket?.remoteAddress || '')) return deny(res, 403, 'loopback only')
    if (!HOST_OK.test(String(req.headers?.host || ''))) return deny(res, 403, 'loopback host only')
    const id = url.slice(LOCAL_VEHICLE_PREFIX.length).replace(/\.glb$/i, '')
    if (!/^[a-z0-9-]{1,32}$/.test(id)) return deny(res, 404, 'unknown asset')
    let file
    try {
      file = readConfig()[id]
    } catch {
      file = undefined
    }
    if (typeof file !== 'string' || path.extname(file).toLowerCase() !== '.glb' || !fs.existsSync(file)) return deny(res, 404, 'asset not available locally')
    const size = fs.statSync(file).size
    res.statusCode = 200
    res.setHeader('Content-Type', 'model/gltf-binary')
    res.setHeader('Content-Length', String(size))
    res.setHeader('Cache-Control', 'no-store')
    res.setHeader('X-Content-Type-Options', 'nosniff')
    res.setHeader('Cross-Origin-Resource-Policy', 'same-origin')
    if (req.method === 'HEAD') return res.end()
    fs.createReadStream(file).pipe(res)
  }
}

export default function localVehicleAssets({ configPath }) {
  const readConfig = () => JSON.parse(fs.readFileSync(path.resolve(configPath), 'utf8'))
  return {
    name: 'fit-ai-local-vehicle-assets',
    apply: 'serve',
    configureServer(server) {
      server.middlewares.use(createHandler(readConfig))
    },
  }
}
