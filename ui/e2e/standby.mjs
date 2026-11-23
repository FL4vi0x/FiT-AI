// Standby screen checks in headless Edge against `vite preview` (no backend): screenshots, overflow, console errors,
// network requests, reduced motion, resize.   npm run build && node e2e/standby.mjs
import { spawn } from 'node:child_process'
import fs from 'node:fs'
import http from 'node:http'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright-core'

const here = path.dirname(fileURLToPath(import.meta.url))
const uiDir = path.resolve(here, '..')
const out = path.join(here, 'out', 'standby')
fs.mkdirSync(out, { recursive: true })
const UI = 'http://127.0.0.1:4174'
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const waitHttp = (url) =>
  new Promise((res, rej) => {
    const go = (n) => http.get(url, (r) => (r.resume(), res())).on('error', () => (n <= 0 ? rej(new Error('no answer')) : setTimeout(() => go(n - 1), 250)))
    go(60)
  })

const preview = spawn(process.execPath, [path.join(uiDir, 'node_modules', 'vite', 'bin', 'vite.js'), 'preview', '--host', '127.0.0.1', '--port', '4174', '--strictPort'], { cwd: uiDir, stdio: 'ignore' })
await waitHttp(`${UI}/`)
const browser = await chromium.launch({ channel: 'msedge', headless: true })
let failed = 0
const check = (ok, msg) => (console.log(`${ok ? 'PASS' : 'FAIL'}  ${msg}`), ok || failed++)

const SIZES = [[1920, 1080], [1600, 900], [1366, 768], [1280, 720], [1024, 600]]
async function open(w, h, reducedMotion = 'no-preference') {
  const ctx = await browser.newContext({ viewport: { width: w, height: h }, reducedMotion })
  const page = await ctx.newPage()
  const logs = { errors: [], requests: [] }
  page.on('console', (m) => m.type() === 'error' && logs.errors.push(m.text()))
  page.on('pageerror', (e) => logs.errors.push(String(e)))
  page.on('request', (r) => !r.url().startsWith(UI) && !r.url().startsWith('data:') && logs.requests.push(r.url()))
  page.on('request', (r) => ['fetch', 'xhr'].includes(r.resourceType()) && logs.requests.push(r.url()))
  await page.goto(`${UI}/`, { waitUntil: 'domcontentloaded' })
  return { ctx, page, logs }
}
const overflow = (page) => page.evaluate(() => ({ x: document.documentElement.scrollWidth - innerWidth, y: document.documentElement.scrollHeight - innerHeight }))

for (const [w, h] of SIZES) {
  const { ctx, page, logs } = await open(w, h)
  await page.getByTestId('standby-screen').waitFor()
  await sleep(3200)
  const phase = await page.getByTestId('standby-screen').getAttribute('data-phase')
  await page.screenshot({ path: path.join(out, `final-${w}x${h}.png`) })
  const o = await overflow(page)
  check(phase === 'idle', `${w}x${h} reaches idle`)
  check(o.x <= 0 && o.y <= 0, `${w}x${h} no overflow (${o.x},${o.y})`)
  check(logs.errors.length === 0, `${w}x${h} no console errors ${logs.errors.join(' | ')}`)
  check(logs.requests.length === 0, `${w}x${h} no network requests ${logs.requests.join(' ')}`)
  await ctx.close()
}

// entrance frames (1366x768)
{
  const { ctx, page } = await open(1366, 768)
  await page.getByTestId('standby-screen').waitFor()
  for (const [ms, name] of [[300, 'a-300'], [700, 'b-1000'], [700, 'c-1700'], [900, 'd-2600']]) {
    await sleep(ms)
    await page.screenshot({ path: path.join(out, `entrance-${name}.png`) })
  }
  await ctx.close()
}

// reduced motion: final state immediately, no loops
for (const [w, h] of [[1920, 1080], [1366, 768], [1024, 600]]) {
  const { ctx, page } = await open(w, h, 'reduce')
  const scr = page.getByTestId('standby-screen')
  await scr.waitFor()
  await sleep(150)
  check((await scr.getAttribute('data-phase')) === 'idle' && (await scr.getAttribute('data-motion')) === 'reduced', `${w}x${h} reduced motion is idle at once`)
  const running = await page.evaluate(() => document.getAnimations().filter((a) => a.playState === 'running').length)
  check(running === 0, `${w}x${h} reduced motion: ${running} running animations`)
  await page.screenshot({ path: path.join(out, `reduced-${w}x${h}.png`) })
  await ctx.close()
}

// resize
{
  const { ctx, page } = await open(1920, 1080)
  await page.getByTestId('standby-screen').waitFor()
  await sleep(3000)
  for (const [w, h] of [[1280, 720], [1024, 600], [1600, 900]]) {
    await page.setViewportSize({ width: w, height: h })
    await sleep(300)
    const o = await overflow(page)
    check(o.x <= 0 && o.y <= 0, `resize to ${w}x${h} no overflow`)
    await page.screenshot({ path: path.join(out, `resized-${w}x${h}.png`) })
  }
  await ctx.close()
}

await browser.close()
preview.kill()
console.log(failed ? `\n${failed} FAILED` : '\nall passed')
process.exit(failed ? 1 : 0)
