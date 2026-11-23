// Rendering cost of the HUD in headless Edge, per state: main-thread busy fraction (Chromium's TaskDuration) and frames
// per second. Headless Edge rasterises in SOFTWARE (no GPU), so these numbers are a pessimistic bound: a GPU makes the
// blur / drop-shadow layers nearly free. Use them to compare states and to catch regressions, not as a frame-rate promise.
//
//   npm run build && node e2e/perf.mjs
import { spawn } from 'node:child_process'
import http from 'node:http'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright-core'
import { startMockCore } from './mock-core.mjs'

const here = path.dirname(fileURLToPath(import.meta.url))
const uiDir = path.resolve(here, '..')
const UI = 'http://127.0.0.1:4173'
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const waitHttp = (url) =>
  new Promise((res, rej) => {
    const go = (n) => http.get(url, (r) => (r.resume(), res())).on('error', () => (n <= 0 ? rej(new Error('no answer')) : setTimeout(() => go(n - 1), 250)))
    go(60)
  })

const mock = await startMockCore({ port: 8010 })
const preview = spawn(process.execPath, [path.join(uiDir, 'node_modules', 'vite', 'bin', 'vite.js'), 'preview', '--host', '127.0.0.1', '--port', '4173', '--strictPort'], {
  cwd: uiDir,
  env: { ...process.env, FIT_AI_CORE_URL: 'http://127.0.0.1:8010' },
  stdio: 'ignore',
})
await waitHttp(`${UI}/`)
const browser = await chromium.launch({ channel: 'msedge', headless: true })
const page = await (await browser.newContext({ viewport: { width: 1600, height: 900 } })).newPage()
const cdp = await page.context().newCDPSession(page)
await cdp.send('Performance.enable')
const t = (id) => page.getByTestId(id)

async function measure(label, ms = 4000) {
  const metric = async () => Object.fromEntries((await cdp.send('Performance.getMetrics')).metrics.map((m) => [m.name, m.value]))
  await page.evaluate(() => {
    window.__frames = 0
    if (!window.__loop) {
      // ONE counting loop for the whole run (a loop per measurement would multiply the count)
      window.__loop = true
      const tick = () => (window.__frames++, requestAnimationFrame(tick))
      requestAnimationFrame(tick)
    }
  })
  const a = await metric()
  const t0 = Date.now()
  await sleep(ms)
  const b = await metric()
  const secs = (Date.now() - t0) / 1000
  const frames = await page.evaluate(() => window.__frames)
  const busy = ((b.TaskDuration - a.TaskDuration) / secs) * 100
  const script = ((b.ScriptDuration - a.ScriptDuration) / secs) * 100
  const layout = ((b.LayoutDuration - a.LayoutDuration + (b.RecalcStyleDuration - a.RecalcStyleDuration)) / secs) * 100
  console.log(`${label.padEnd(34)} main thread busy ${busy.toFixed(0).padStart(3)}%  (script ${script.toFixed(0)}%, layout+style ${layout.toFixed(0)}%)   ${(frames / secs).toFixed(0)} fps`)
  await page.evaluate(() => (window.__frames = 0))
}

console.log('\nFit AI UI · rendering cost, headless Edge, SOFTWARE rasterisation (pessimistic), 1600x900\n')
await page.goto(UI + '/#/hud', { waitUntil: 'domcontentloaded' })
await t('status-cluster').waitFor()
await sleep(3500) // the car has drawn itself and the one-time waking pass is over
await measure('idle (car, a quiet core)')

mock.configure({ latency: { telemetry: 60_000 } })
await page.evaluate(() => document.querySelector('[data-testid=scan-button]').click())
await sleep(1500)
await measure('scanning (sweep + 9 pulsing nodes)')
mock.configure({ reset: true, latency: { telemetry: 0 } })
await t('clear-button').click()
await sleep(600)

await t('scan-button').click()
await t('callout-rpm').waitFor()
await sleep(1500)
await measure('presenting (3 callouts + system)')

mock.configure({ chat: { kind: 'auto' }, latency: { chat: 60_000 } })
await t('clear-button').click()
await t('chat-input').fill('Qual a rotação?')
await t('chat-input').press('Enter')
await sleep(1500)
await measure('thinking (core orbit + 4 bus lines)')

await browser.close()
preview.kill()
await mock.close()
process.exit(0)
