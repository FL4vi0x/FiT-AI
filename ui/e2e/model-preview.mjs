// LOCAL PREVIEW of the vehicle models A and C inside the real active screen (headless Edge, real WebGL via the software rasteriser).
// Starts the DEV server (the only place the local asset route exists) on loopback, plus the mock Core. Nothing here is published:
// screenshots go to assets/honda-fit-gd/out/previews/ (git-ignored).        node e2e/model-preview.mjs
import { spawn } from 'node:child_process'
import fs from 'node:fs'
import http from 'node:http'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright-core'
import { startMockCore } from './mock-core.mjs'

const here = path.dirname(fileURLToPath(import.meta.url))
const uiDir = path.resolve(here, '..')
const previews = path.resolve(uiDir, '..', 'assets', 'honda-fit-gd', 'out', 'previews')
fs.mkdirSync(previews, { recursive: true })
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const waitHttp = (u) => new Promise((res, rej) => { const go = (n) => http.get(u, (r) => (r.resume(), res())).on('error', () => (n <= 0 ? rej(new Error('no answer')) : setTimeout(() => go(n - 1), 250))); go(80) })
const vite = path.join(uiDir, 'node_modules', 'vite', 'bin', 'vite.js')
const dev = (port, extraEnv = {}) => spawn(process.execPath, [vite, '--host', '127.0.0.1', '--port', String(port), '--strictPort'], { cwd: uiDir, stdio: 'ignore', env: { ...process.env, FIT_AI_CORE_URL: 'http://127.0.0.1:8010', ...extraEnv } })
const get = (url, headers = {}) => new Promise((res, rej) => http.get(url, { headers }, (r) => { const ch = []; r.on('data', (c) => ch.push(c)); r.on('end', () => res({ status: r.statusCode, type: r.headers['content-type'], len: Buffer.concat(ch).length })) }).on('error', rej))

const mock = await startMockCore({ port: 8010 })
const server = dev(5180)
const serverNoConfig = dev(5181, { FIT_LOCAL_VEHICLE_CONFIG: path.join(previews, 'does-not-exist.json') })
const UP = 'http://127.0.0.1:5180'
const NOCONF = 'http://127.0.0.1:5181'
await waitHttp(UP + '/')
await waitHttp(NOCONF + '/')
const browser = await chromium.launch({ channel: 'msedge', headless: true })
let failed = 0
const check = (ok, msg) => (console.log(`${ok ? 'PASS' : 'FAIL'}  ${msg}`), ok || failed++)
const metrics = {}

async function open(base, hash, w = 1920, h = 1080, reducedMotion = 'reduce', dsf = 1) {
  const ctx = await browser.newContext({ viewport: { width: w, height: h }, reducedMotion, deviceScaleFactor: dsf })
  const page = await ctx.newPage()
  const logs = { errors: [], requests: [] }
  page.on('console', (m) => m.type() === 'error' && logs.errors.push(m.text()))
  page.on('pageerror', (e) => logs.errors.push(String(e)))
  page.on('request', (r) => logs.requests.push(new URL(r.url())))
  const t0 = Date.now()
  await page.goto(`${base}/${hash}`, { waitUntil: 'domcontentloaded' })
  return { ctx, page, logs, t0 }
}
const ds = (page) => page.getByTestId('vehicle-canvas').evaluate((c) => ({ ...c.dataset }))
async function until(fn, ms = 40000) { const t = Date.now(); for (;;) { try { const v = await fn(); if (v) return v } catch { /* retry */ } if (Date.now() - t > ms) return null; await sleep(250) } }
async function loaded(page, want = 'loaded') { return until(async () => { const d = await ds(page); return d.modelState === want ? d : null }) }
const overflow = (page) => page.evaluate(() => ({ x: document.documentElement.scrollWidth - innerWidth, y: document.documentElement.scrollHeight - innerHeight }))

// ───────── 0. the route is dev-only and loopback-only ─────────
{
  const ok = await get(UP + '/__local_vehicle/model-c.glb')
  check(ok.status === 200 && ok.type === 'model/gltf-binary' && ok.len > 100000, `dev server serves the local asset on loopback (${ok.status}, ${ok.type}, ${(ok.len / 1024).toFixed(0)} KB)`)
  const spoof = await get(UP + '/__local_vehicle/model-c.glb', { Host: 'example.com' })
  check(spoof.status === 403, `a non-loopback Host header is refused (${spoof.status})`)
  const trav = await get(UP + '/__local_vehicle/..%2F..%2Fpackage.json')
  check(trav.status === 404, `a path-looking id is refused (${trav.status})`)
  const unknown = await get(UP + '/__local_vehicle/model-z.glb')
  check(unknown.status === 404, `an id missing from the local config is 404 (${unknown.status})`)
}

// ───────── 1. model C and model A load inside the real screen (1920x1080, reduced motion = a still, comparable frame) ─────────
for (const id of ['model-c', 'model-a']) {
  const { ctx, page, logs, t0 } = await open(UP, `#/active?vehicle=${id}`)
  await page.getByTestId('active-screen').waitFor()
  const d = await loaded(page)
  const loadedAfter = Date.now() - t0
  check(!!d, `${id}: loaded in the browser (state ${d?.modelState})`)
  if (d) {
    metrics[id] = { tris: d.modelTris, meshes: d.modelMeshes, size: d.modelSize, loadMs: d.modelLoadMs, pageToLoadedMs: loadedAfter }
    await sleep(2500) // reveal + a few frames
    const d2 = await ds(page)
    Object.assign(metrics[id], { calls: d2.calls, drawnTriangles: d2.triangles, geometries: d2.geometries, textures: d2.textures, programs: d2.programs })
    const [L, Wd, H] = d2.modelSize.split('x').map(Number)
    check(Math.abs(L - 3.83) < 0.01 && H > 1.3 && H < 2.1 && Wd > 1.5 && Wd < 2.1, `${id}: normalised to a car-sized box (${d2.modelSize} m, uniform scale)`)
    const base = `model-${id === 'model-c' ? 'c' : 'a'}-active`
    await page.screenshot({ path: path.join(previews, `${base}-front34.png`) })
  }
  const o = await overflow(page)
  check(o.x <= 0 && o.y <= 0, `${id}: no overflow`)
  check(logs.errors.length === 0, `${id}: no console errors ${logs.errors.join(' | ').slice(0, 200)}`)
  const ext = logs.requests.filter((u) => /^https?:$/.test(u.protocol) && !['127.0.0.1', 'localhost'].includes(u.hostname)) // blob: / data: are local decodes, not network
  check(ext.length === 0, `${id}: every request stays on loopback`)
  check(logs.requests.some((u) => u.pathname === `/__local_vehicle/${id}.glb`), `${id}: asset fetched from the local dev route only`)
  await ctx.close()
}

// ───────── 1b. the machine-local default: opening the active screen with NO vehicle in the URL shows model C ─────────
{
  const { ctx, page } = await open(UP, '#/active')
  await page.getByTestId('active-screen').waitFor()
  const d = await loaded(page)
  check(!!d && d.vehicleAsset === 'model-c', `default vehicle on this machine is model C (${d?.vehicleAsset})`)
  await page.screenshot({ path: path.join(previews, 'model-c-active-default.png') })
  await ctx.close()
  const forced = await open(UP, '#/active?vehicle=placeholder')
  await forced.page.getByTestId('active-screen').waitFor()
  await sleep(2500)
  const f = await ds(forced.page)
  check(f.vehicleAsset === 'placeholder' && f.modelState === 'placeholder', 'vehicle=placeholder still gives the procedural car (reversible)')
  await forced.ctx.close()
}

// ───────── 2. views, looks (C and A, same camera / frame / light / resolution) ─────────
for (const id of ['model-c', 'model-a']) {
  const tag = id === 'model-c' ? 'c' : 'a'
  for (const [name, hash] of [['side', `#/active?vehicle=${id}&yaw=-35.5`], ['rear34', `#/active?vehicle=${id}&yaw=-71`], ['grey', `#/active?vehicle=${id}&look=grey`], ['original', `#/active?vehicle=${id}&look=original`]]) {
    const { ctx, page } = await open(UP, hash)
    await page.getByTestId('active-screen').waitFor()
    await loaded(page)
    await sleep(2200)
    await page.screenshot({ path: path.join(previews, `model-${tag}-active-${name}.png`) })
    await ctx.close()
  }
  // close-up of the hologram itself (clip on the vehicle area, 2x)
  const { ctx, page } = await open(UP, `#/active?vehicle=${id}`, 1920, 1080, 'reduce', 2)
  await page.getByTestId('active-screen').waitFor()
  await loaded(page)
  await sleep(2200)
  const box = await page.getByTestId('vehicle-stage').boundingBox()
  await page.screenshot({ path: path.join(previews, `model-${tag}-active-hologram.png`), clip: box })
  await ctx.close()
}
check(['front34', 'side', 'rear34', 'hologram', 'grey'].every((n) => fs.existsSync(path.join(previews, `model-c-active-${n}.png`))), 'the five required model-c screenshots exist')

// ───────── 3. dev panel: switch models and looks, reset camera, no leaked GPU objects ─────────
{
  const { ctx, page, logs } = await open(UP, '#/active?demo&vehicle=model-c')
  await page.getByTestId('dev-vehicle-panel').waitFor()
  await loaded(page)
  const g0 = Number((await ds(page)).geometries)
  const seq = []
  for (const id of ['model-a', 'model-c', 'model-a', 'model-c']) {
    await page.getByTestId(`dev-asset-${id}`).click()
    const d = await until(async () => { const x = await ds(page); return x.vehicleAsset === id && x.modelState === 'loaded' ? x : null })
    check(!!d, `switch to ${id} works`)
    await sleep(1200)
    seq.push(Number((await ds(page)).geometries))
  }
  await page.getByTestId('dev-asset-placeholder').click()
  await sleep(1500)
  const gPh = Number((await ds(page)).geometries)
  check(Math.max(...seq) <= Math.max(g0, ...seq.slice(0, 2)) + 2, `no GPU geometry leak across 4 switches (counts ${[g0, ...seq, gPh].join(' -> ')})`)
  await page.getByTestId('dev-asset-model-c').click()
  await until(async () => { const x = await ds(page); return x.vehicleAsset === 'model-c' && x.modelState === 'loaded' })
  await page.getByTestId('dev-look-grey').click()
  await sleep(500)
  check((await ds(page)).appearance === 'grey', 'grey look on')
  await page.getByTestId('dev-look-hologram').click()
  await sleep(300)
  check((await ds(page)).appearance === 'hologram', 'hologram look back (reversible)')
  const before = (await ds(page)).yaw
  const bb = await page.getByTestId('vehicle-canvas').boundingBox()
  await page.mouse.move(bb.x + bb.width / 2, bb.y + bb.height / 2)
  await page.mouse.down(); await page.mouse.move(bb.x + bb.width / 2 + 120, bb.y + bb.height / 2, { steps: 6 }); await page.mouse.up()
  await sleep(300)
  const dragged = (await ds(page)).yaw
  check(before !== dragged, `drag turns the car (${before} -> ${dragged})`)
  await page.getByTestId('dev-reset-view').click()
  await sleep(300)
  check(Math.abs(Number((await ds(page)).yaw) - (Math.PI + 0.9)) < 0.25, 'reset restores the three-quarter view')
  check(logs.errors.length === 0, `switching: no console errors ${logs.errors.join(' | ').slice(0, 160)}`)
  await ctx.close()
}

// ───────── 4. missing model: the placeholder stays, honestly labelled ─────────
{
  const { ctx, page, logs } = await open(NOCONF, '#/active?vehicle=model-c')
  await page.getByTestId('active-screen').waitFor()
  const d = await loaded(page, 'missing')
  check(!!d, 'missing local asset -> modelState "missing"')
  const badge = await page.getByTestId('dev-badge').textContent()
  check(/AUSENTE/.test(badge || ''), `badge says so: "${badge}"`)
  check((await page.getByTestId('vehicle-notice').count()) === 0 && (await page.getByTestId('vehicle-canvas').count()) === 1, 'the HUD and the procedural car are still there')
  check(logs.errors.every((e) => /404|Failed to load resource/.test(e)), 'only the expected 404 is logged for the missing asset')
  await ctx.close()
}

// ───────── 5. responsive: 1920x1080, 1366x768, 1280x720, 1024x600 ─────────
for (const [w, h] of [[1920, 1080], [1366, 768], [1280, 720], [1024, 600]]) {
  const { ctx, page, logs } = await open(UP, '#/active?vehicle=model-c', w, h)
  await page.getByTestId('active-screen').waitFor()
  const d = await loaded(page)
  await sleep(2200)
  const o = await overflow(page)
  check(!!d && o.x <= 0 && o.y <= 0, `${w}x${h}: model C on stage, no overflow`)
  check(logs.errors.length === 0, `${w}x${h}: no console errors`)
  await page.screenshot({ path: path.join(previews, `model-c-active-${w}x${h}.png`) })
  await ctx.close()
}

// ───────── 6. motion: ambient rotation, pause when hidden, reduced motion ─────────
{
  const { ctx, page } = await open(UP, '#/active?vehicle=model-c', 1366, 768, 'no-preference')
  await page.getByTestId('active-screen').waitFor()
  await loaded(page)
  await sleep(3500)
  const a = Number((await ds(page)).yaw); await sleep(4000); const b = Number((await ds(page)).yaw)
  check(a !== b && Math.abs(b - a) < 0.2, `model C: slow ambient rotation (${a} -> ${b})`)
  await page.evaluate(() => { Object.defineProperty(document, 'hidden', { value: true, configurable: true }); document.dispatchEvent(new Event('visibilitychange')) })
  await sleep(300); const c = (await ds(page)).yaw; await sleep(2000)
  check(c === (await ds(page)).yaw, 'paused while the tab is hidden')
  await ctx.close()
  const r = await open(UP, '#/active?vehicle=model-c', 1366, 768, 'reduce')
  await r.page.getByTestId('active-screen').waitFor(); await loaded(r.page); await sleep(1500)
  const y1 = (await ds(r.page)).yaw; await sleep(2500)
  check(y1 === (await ds(r.page)).yaw, 'reduced motion: the car does not rotate')
  await r.ctx.close()
}

// ───────── 7. performance (headless Edge, SOFTWARE rasterisation: pessimistic) ─────────
for (const id of ['model-c', 'model-a', 'placeholder']) {
  const { ctx, page } = await open(UP, id === 'placeholder' ? '#/active' : `#/active?vehicle=${id}`, 1920, 1080, 'no-preference')
  await page.getByTestId('active-screen').waitFor()
  if (id !== 'placeholder') await loaded(page)
  await sleep(5000)
  const cdp = await ctx.newCDPSession(page)
  await cdp.send('Performance.enable')
  await page.evaluate(() => { window.__f = 0; const t = () => (window.__f++, requestAnimationFrame(t)); requestAnimationFrame(t) })
  const m = async () => Object.fromEntries((await cdp.send('Performance.getMetrics')).metrics.map((x) => [x.name, x.value]))
  const a = await m(); const t0 = Date.now(); await sleep(6000); const b = await m()
  const secs = (Date.now() - t0) / 1000
  const frames = await page.evaluate(() => window.__f)
  const d = await ds(page)
  metrics[`perf-${id}`] = { busyPct: Math.round(((b.TaskDuration - a.TaskDuration) / secs) * 100), rafPerSec: Math.round(frames / secs), heapMB: Math.round(b.JSHeapUsedSize / 1048576), calls: d.calls, triangles: d.triangles, geometries: d.geometries, textures: d.textures }
  await ctx.close()
}

await browser.close()
server.kill(); serverNoConfig.kill(); await mock.close()
console.log('\nMETRICS ' + JSON.stringify(metrics, null, 1))
fs.writeFileSync(path.join(previews, 'metrics.json'), JSON.stringify(metrics, null, 2))
console.log(failed ? `\n${failed} FAILED` : '\nall passed')
process.exit(failed ? 1 : 0)
