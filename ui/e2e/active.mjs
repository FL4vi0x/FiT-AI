// Active screen (P8.2) in headless Edge: screenshots, overflow, console errors, requests, WebGL car, rotation, pause, transition,
// reduced motion, Core offline, performance.   npm run build && node e2e/active.mjs
import { spawn } from 'node:child_process'
import fs from 'node:fs'
import http from 'node:http'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright-core'
import { startMockCore } from './mock-core.mjs'

const here = path.dirname(fileURLToPath(import.meta.url))
const uiDir = path.resolve(here, '..')
const out = path.join(here, 'out', 'active')
fs.mkdirSync(out, { recursive: true })
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const waitHttp = (u) => new Promise((res, rej) => { const go = (n) => http.get(u, (r) => (r.resume(), res())).on('error', () => (n <= 0 ? rej(new Error('no answer')) : setTimeout(() => go(n - 1), 250))); go(60) })
const vite = path.join(uiDir, 'node_modules', 'vite', 'bin', 'vite.js')
const preview = (port, core) => spawn(process.execPath, [vite, 'preview', '--host', '127.0.0.1', '--port', String(port), '--strictPort'], { cwd: uiDir, stdio: 'ignore', env: { ...process.env, FIT_AI_CORE_URL: core } })

const mock = await startMockCore({ port: 8010 })
const withCore = preview(4177, 'http://127.0.0.1:8010')
const noCore = preview(4178, 'http://127.0.0.1:8099') // nothing listens there
const UP = 'http://127.0.0.1:4177'
const DOWN = 'http://127.0.0.1:4178'
await waitHttp(UP + '/')
await waitHttp(DOWN + '/')
const browser = await chromium.launch({ channel: 'msedge', headless: true })
let failed = 0
const check = (ok, msg) => (console.log(`${ok ? 'PASS' : 'FAIL'}  ${msg}`), ok || failed++)

async function open(base, hash, w, h, reducedMotion = 'no-preference') {
  const ctx = await browser.newContext({ viewport: { width: w, height: h }, reducedMotion })
  const page = await ctx.newPage()
  const logs = { errors: [], requests: [] }
  page.on('console', (m) => m.type() === 'error' && logs.errors.push(m.text()))
  page.on('pageerror', (e) => logs.errors.push(String(e)))
  page.on('request', (r) => ['fetch', 'xhr'].includes(r.resourceType()) && logs.requests.push(new URL(r.url()).pathname))
  await page.goto(`${base}/${hash}`, { waitUntil: 'domcontentloaded' })
  return { ctx, page, logs }
}
const overflow = (page) => page.evaluate(() => ({ x: document.documentElement.scrollWidth - innerWidth, y: document.documentElement.scrollHeight - innerHeight }))
const yaw = (page) => page.getByTestId('vehicle-canvas').evaluate((c) => Number(c.dataset.yaw))

for (const [w, h] of [[1920, 1080], [1600, 900], [1366, 768], [1280, 720], [1024, 600]]) {
  const { ctx, page, logs } = await open(UP, '#/active', w, h)
  await page.getByTestId('active-screen').waitFor()
  await sleep(4800)
  const tag = `${w}x${h}`
  check((await page.getByTestId('active-screen').getAttribute('data-state')) === 'active', `${tag} reaches active (Core up)`)
  const o = await overflow(page)
  check(o.x <= 0 && o.y <= 0, `${tag} no overflow (${o.x},${o.y})`)
  check(logs.errors.length === 0, `${tag} no console errors ${logs.errors.join(' | ')}`)
  const paths = [...new Set(logs.requests)]
  check(paths.every((p) => p === '/health' || p === '/api/v1/vehicle/status') && paths.length > 0, `${tag} requests are only the two read-only checks: ${paths.join(', ')}`)
  check((await page.getByTestId('vehicle-notice').count()) === 0 && (await page.getByTestId('vehicle-canvas').count()) === 1, `${tag} WebGL car rendered (no fallback notice)`)
  const hdr = await page.getByTestId('active-header').boundingBox()
  const overlap = await page.evaluate(() => [...document.querySelectorAll('header *')].filter((e) => !/srOnly/.test(e.className)).some((e) => e.scrollWidth > e.clientWidth + 1 && getComputedStyle(e).overflow !== 'visible'))
  check(hdr.width <= w && !overlap, `${tag} header fits (${Math.round(hdr.width)} px, nothing clipped)`)
  await page.screenshot({ path: path.join(out, `active-${tag}.png`) })
  await ctx.close()
}

// ambient rotation, slow and bounded; pause when the tab is hidden
{
  const { ctx, page } = await open(UP, '#/active', 1366, 768)
  await page.getByTestId('vehicle-canvas').waitFor()
  await sleep(3500)
  const a = await yaw(page)
  await sleep(4000)
  const b = await yaw(page)
  check(a !== b && Math.abs(b - a) < 0.2, `ambient rotation moves slowly (${a} -> ${b})`)
  await page.evaluate(() => { Object.defineProperty(document, 'hidden', { value: true, configurable: true }); document.dispatchEvent(new Event('visibilitychange')) })
  await sleep(300)
  const c = await yaw(page)
  await sleep(2000)
  const d = await yaw(page)
  check(c === d, `rotation paused while the tab is hidden (${c} = ${d})`)
  await page.evaluate(() => { Object.defineProperty(document, 'hidden', { value: false, configurable: true }); document.dispatchEvent(new Event('visibilitychange')) })
  await sleep(2500)
  check((await yaw(page)) !== d, 'rotation resumes when the tab is visible again')
  await ctx.close()
}

// Standby -> Active, frame by frame
{
  const { ctx, page, logs } = await open(UP, '', 1366, 768)
  await page.getByTestId('wake').waitFor()
  await sleep(2800)
  check(logs.requests.length === 0, 'Standby makes no request')
  await page.getByTestId('wake').click()
  let t = 0
  for (const at of [250, 800, 1500, 2200, 3000, 3800]) {
    await sleep(at - t)
    t = at
    await page.screenshot({ path: path.join(out, `transition-${String(at).padStart(4, '0')}.png`) })
  }
  await sleep(1000)
  check((await page.getByTestId('active-screen').getAttribute('data-state')) === 'active', 'transition ends in active')
  check((await page.getByTestId('standby-layer').count()) === 0, 'Standby layer removed after the contraction')
  const paths = [...new Set(logs.requests)]
  check(paths.every((p) => p === '/health' || p === '/api/v1/vehicle/status'), `no chat/telemetry call during the transition: ${paths.join(', ')}`)
  await ctx.close()
}

// reduced motion
{
  const { ctx, page } = await open(UP, '#/active', 1366, 768, 'reduce')
  const scr = page.getByTestId('active-screen')
  await scr.waitFor()
  await sleep(1200)
  check((await scr.getAttribute('data-state')) === 'active' && (await scr.getAttribute('data-motion')) === 'reduced', 'reduced motion: active at once')
  const running = await page.evaluate(() => document.getAnimations().filter((a) => a.playState === 'running').length)
  check(running === 0, `reduced motion: ${running} running CSS animations`)
  const a = await yaw(page)
  await sleep(2500)
  check(a === (await yaw(page)), 'reduced motion: the car does not rotate')
  await page.screenshot({ path: path.join(out, 'reduced-1366x768.png') })
  await ctx.close()
}

// Core offline: honest status, no fake "online"
{
  const { ctx, page } = await open(DOWN, '#/active', 1366, 768)
  await page.getByTestId('active-screen').waitFor()
  await sleep(5000)
  check((await page.getByTestId('active-screen').getAttribute('data-state')) === 'unavailable', 'Core offline: state unavailable')
  check((await page.getByTestId('system-line').textContent()) === 'Sistema desconectado', 'Core offline: header says disconnected')
  const chip = await page.getByTestId('chip-octave').textContent()
  check(/Sem Core/.test(chip) && !/Conectado/.test(chip), `Core offline: OCTAVE chip "${chip}"`)
  await page.screenshot({ path: path.join(out, 'offline-1366x768.png') })
  await ctx.close()
}

// resize
{
  const { ctx, page } = await open(UP, '#/active', 1920, 1080)
  await page.getByTestId('vehicle-canvas').waitFor()
  await sleep(3500)
  for (const [w, h] of [[1280, 720], [1024, 600], [1600, 900]]) {
    await page.setViewportSize({ width: w, height: h })
    await sleep(400)
    const o = await overflow(page)
    check(o.x <= 0 && o.y <= 0, `resize to ${w}x${h} no overflow`)
    await page.screenshot({ path: path.join(out, `resized-${w}x${h}.png`) })
  }
  await ctx.close()
}

// performance (headless Edge, SOFTWARE rendering: pessimistic)
{
  const { ctx, page } = await open(UP, '#/active', 1920, 1080)
  await page.getByTestId('vehicle-canvas').waitFor()
  await sleep(5000)
  const cdp = await ctx.newCDPSession(page)
  await cdp.send('Performance.enable')
  await page.evaluate(() => { window.__f = 0; const t = () => (window.__f++, requestAnimationFrame(t)); requestAnimationFrame(t) })
  const m = async () => Object.fromEntries((await cdp.send('Performance.getMetrics')).metrics.map((x) => [x.name, x.value]))
  const a = await m(); const t0 = Date.now(); await sleep(6000); const b = await m()
  const secs = (Date.now() - t0) / 1000
  const frames = await page.evaluate(() => window.__f)
  console.log(`INFO  1920x1080 active idle (software rendering): main thread busy ${(((b.TaskDuration - a.TaskDuration) / secs) * 100).toFixed(0)}%, ${(frames / secs).toFixed(0)} rAF/s, JS heap ${(b.JSHeapUsedSize / 1048576).toFixed(0)} MB`)
  await ctx.close()
}

await browser.close()
withCore.kill()
noCore.kill()
await mock.close()
console.log(failed ? `\n${failed} FAILED` : '\nall passed')
process.exit(failed ? 1 : 0)
