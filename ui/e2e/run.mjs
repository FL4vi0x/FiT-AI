// End-to-end run of the BUILT UI (vite preview, production CSP) against the stand-in Core, driven by the installed Microsoft
// Edge in headless mode through playwright-core (no browser download, no desktop input). Saves screenshots to e2e/out/.
//
//   npm run build && npm run e2e
//
// All waits happen on the Node side (locator.waitFor / until): the page's production CSP forbids 'unsafe-eval', which
// Playwright's page.waitForFunction needs, and the CSP is part of what is under test.
import { spawn } from 'node:child_process'
import fs from 'node:fs'
import http from 'node:http'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright-core'
import { startMockCore } from './mock-core.mjs'

const here = path.dirname(fileURLToPath(import.meta.url))
const uiDir = path.resolve(here, '..')
const outDir = path.join(here, 'out')
fs.rmSync(outDir, { recursive: true, force: true })
fs.mkdirSync(outDir, { recursive: true })

const MOCK_PORT = 8010
const UI_PORT = 4173
const UI = `http://127.0.0.1:${UI_PORT}`

const results = []
async function step(name, fn) {
  const t0 = Date.now()
  try {
    await fn()
    results.push({ name, ok: true, ms: Date.now() - t0 })
    console.log(`  PASS  ${name}`)
  } catch (e) {
    results.push({ name, ok: false, ms: Date.now() - t0, err: String(e?.message ?? e).split('\n')[0] })
    console.log(`  FAIL  ${name}\n        ${String(e?.message ?? e).split('\n')[0]}`)
  }
}
function assert(cond, msg) {
  if (!cond) throw new Error(msg)
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
async function until(fn, timeout = 10000, msg = 'condition') {
  const end = Date.now() + timeout
  let last
  while (Date.now() < end) {
    try {
      if (await fn()) return
    } catch (e) {
      last = e
    }
    await sleep(150)
  }
  throw new Error(`timed out waiting for ${msg}${last ? ` (${String(last.message).split('\n')[0]})` : ''}`)
}

function waitHttp(url, tries = 60) {
  return new Promise((resolve, reject) => {
    const attempt = (n) =>
      http
        .get(url, (r) => (r.resume(), resolve()))
        .on('error', () => (n <= 0 ? reject(new Error(`no answer from ${url}`)) : setTimeout(() => attempt(n - 1), 250)))
    attempt(tries)
  })
}

let mock = await startMockCore({ port: MOCK_PORT })
const viteBin = path.join(uiDir, 'node_modules', 'vite', 'bin', 'vite.js')
const preview = spawn(process.execPath, [viteBin, 'preview', '--host', '127.0.0.1', '--port', String(UI_PORT), '--strictPort'], {
  cwd: uiDir,
  env: { ...process.env, FIT_AI_CORE_URL: `http://127.0.0.1:${MOCK_PORT}` },
  stdio: 'ignore',
})
const cleanup = async () => {
  preview.kill()
  await mock?.close().catch(() => {})
}
process.on('exit', () => preview.kill())

let browser
try {
  await waitHttp(`${UI}/`)
  browser = await chromium.launch({ channel: 'msedge', headless: true })
} catch (e) {
  console.error('could not start the stack or the browser:', e.message)
  await cleanup()
  process.exit(2)
}

const ctx = await browser.newContext({ viewport: { width: 1600, height: 900 } })
const page = await ctx.newPage()
const consoleErrors = []
const foreign = []
page.on('console', (m) => m.type() === 'error' && consoleErrors.push(m.text()))
page.on('pageerror', (e) => consoleErrors.push(`pageerror: ${e.message}`))
page.on('request', (r) => {
  if (!r.url().startsWith(UI) && !r.url().startsWith('data:')) foreign.push(r.url())
})

const t = (id) => page.getByTestId(id)
const count = (id) => t(id).count()
const text = async (id) => (await t(id).first().textContent()) ?? ''
const attr = (id, a) => t(id).first().getAttribute(a)
const shot = (n, name) => page.screenshot({ path: path.join(outDir, `${String(n).padStart(2, '0')}-${name}.png`) })
const mode = (m, timeout = 15000) => page.locator(`[data-testid=app][data-mode=${m}]`).waitFor({ timeout })
const coreState = () => t('fit-ai-core').getAttribute('data-state')
const calls = (p) => mock.calls.filter((c) => c.path === p).length
const send = async (msg) => {
  await t('chat-input').fill(msg)
  await t('chat-input').press('Enter')
}
async function toIdle() {
  if (await count('clear-button')) await t('clear-button').click()
  await mode('idle', 8000)
}

console.log('\nFit AI UI · end-to-end (Edge headless, built bundle, stand-in Core)\n')

await step('01 boot: real health + status checks; the screen stays clean (one indicator, nothing projected)', async () => {
  mock.configure({ reset: true })
  await page.goto(UI + '/#/hud', { waitUntil: 'domcontentloaded' })
  await until(async () => (await attr('status-cluster', 'data-octave')) === 'connected', 10000, 'OCTAVE connected')
  assert((await attr('status-cluster', 'data-core')) === 'online', 'Core online')
  assert((await attr('status-cluster', 'data-simulated')) === 'true', 'the source is flagged as simulated')
  assert((await text('status-cluster')).includes('Simulador OCTAVE'), 'one sentence for the link')
  assert((await attr('status-cluster', 'data-ollama')) === 'unknown', 'Ollama is unknown until the first chat')
  assert((await coreState()) === 'idle', 'core should be idle')
  assert((await count('callout-system')) === 0 && (await count('callout-rpm')) === 0 && (await count('provenance')) === 0, 'nothing projected at start-up')
  await sleep(2400)
  await shot(1, 'boot')
})

await step('02 idle: car, a quiet core and the chat; the real boot lines are one click away', async () => {
  await mode('idle')
  assert((await count('suggestions')) === 1, 'three suggestions on an empty conversation')
  await t('status-cluster').click()
  await t('status-popover').waitFor()
  assert((await text('status-core')).includes('online'), 'popover has the Core row')
  assert((await text('status-octave')).includes('dados simulados'), 'popover says the data is simulated')
  assert((await text('activity-feed')).includes('core'), 'the feed has the real boot lines')
  await shot(2, 'status')
  await page.keyboard.press('Escape')
  await until(async () => (await count('status-popover')) === 0, 2000, 'the popover to close')
  await sleep(600)
  await shot(3, 'idle')
})

await step('03 scan: sweep + scanning core, then floating readings and ONE provenance line', async () => {
  mock.configure({ latency: { telemetry: 6000 } }) // below the client's 8 s GET timeout
  await t('scan-button').click()
  await mode('scanning', 5000)
  assert((await coreState()) === 'scanning', 'core should be scanning')
  assert((await count('scan-layer')) === 1, 'scan layer should exist while scanning')
  assert((await count('bus-cabin')) === 1, 'faint core-to-module links are drawn')
  await sleep(1200)
  await shot(4, 'scanning')
  mock.configure({ latency: { telemetry: 0 } })
  await mode('presenting', 15000)
  await t('callout-rpm').waitFor()
  assert((await text('callout-rpm-value')) === '820', 'rpm value should be 820')
  assert((await text('callout-speed-value')) === '0', 'speed value should be 0')
  assert((await text('callout-temp-value')) === '90', 'temperature value should be 90')
  assert((await page.locator('[data-testid=callout-rpm] [role=meter]').getAttribute('aria-valuenow')) === '820', 'gauge exposes the value')
  assert(/^Simulado · lido (agora|há \d+ s)$/.test((await text('provenance-text')).trim()), `provenance line: ${await text('provenance-text')}`)
  for (const id of ['callout-rpm', 'callout-speed', 'callout-temp']) assert(!/simulad|agora|há \d/i.test(await text(id)), `${id} must not repeat the provenance`)
  await sleep(1400)
  await shot(5, 'presenting')
})

await step('04 live mode refreshes the reading; clear returns to idle and stops all polling', async () => {
  await t('live-button').click()
  assert((await t('live-button').getAttribute('aria-pressed')) === 'true', 'live toggled on')
  const before = calls('/api/v1/vehicle/telemetry')
  await sleep(4800)
  const after = calls('/api/v1/vehicle/telemetry')
  assert(after >= before + 2, `live should poll telemetry (calls ${before} -> ${after})`)
  await t('clear-button').click()
  await mode('idle', 4000)
  const frozen = calls('/api/v1/vehicle/telemetry')
  await sleep(2800)
  assert(calls('/api/v1/vehicle/telemetry') === frozen, 'no telemetry polling while idle')
})

await step('05 chat: thinking state, then a plain answer with one quiet line; details only on request', async () => {
  mock.configure({ reset: true, latency: { telemetry: 300, chat: 9000 } })
  await send('Qual a rotação do motor?')
  await mode('thinking', 4000)
  assert((await coreState()) === 'thinking', 'core should be thinking')
  assert(await t('thinking-indicator').isVisible(), 'thinking indicator visible')
  assert((await count('bus-powertrain')) === 1, 'faint core-to-module links while thinking')
  assert((await t('chat-input').inputValue()) === '', 'the question left the box at once')
  await sleep(1500)
  await shot(6, 'thinking')
  mock.configure({ latency: { chat: 0 } })
  await t('message-assistant').waitFor({ timeout: 15000 })
  assert((await text('message-summary')).includes('Consultou a telemetria · dados simulados'), 'the quiet line')
  assert((await count('tool-badge')) === 0, 'no tool pill painted on the answer')
  assert((await text('message-assistant')).includes('820'), 'answer text has the value')
  await mode('presenting', 8000)
  await t('callout-rpm').waitFor()
  assert((await attr('status-cluster', 'data-ollama')) === 'online', 'Ollama is inferred online after a model answer')
  await t('message-info').first().click()
  const info = await text('message-info-popover')
  assert(info.includes('Escrita pelo modelo') && info.includes('conferidos pelo sistema'), 'details on request')
  assert((await text('tool-badge')).includes('somente leitura'), 'the tool says it only reads')
  await sleep(1400)
  await shot(7, 'chat-presenting')
})

await step('06 fallback is announced in words under the answer, never silent', async () => {
  mock.configure({ chat: { kind: 'fallback' } })
  await send('Qual a velocidade?')
  await until(async () => (await count('message-assistant')) >= 2, 10000, 'the second answer')
  const last = t('message-assistant').last()
  assert((await last.locator('[data-testid=note-fallback]').count()) === 1, 'fallback note')
  assert(((await last.locator('[data-testid=note-fallback]').textContent()) ?? '').includes('sem o modelo'), 'fallback wording')
  await sleep(600)
  await shot(8, 'fallback')
})

await step('07 partial reading: missing fields say "indisponível" (never zero)', async () => {
  await toIdle()
  mock.configure({ reset: true, telemetry: { kind: 'partial' } })
  await t('scan-button').click()
  await mode('presenting', 8000)
  await t('callout-speed').waitFor({ timeout: 6000 })
  assert((await text('callout-rpm-value')) === '820', 'rpm is still shown')
  assert((await text('callout-speed')).includes('indisponível'), 'speed says indisponível')
  assert((await count('callout-speed-value')) === 0, 'no numeric value for the missing speed')
  assert((await page.locator('[data-testid=callout-speed] [data-testid=telemetry-gauge]').getAttribute('data-available')) === 'false', 'the track is empty')
  await sleep(1500)
  await shot(9, 'partial')
})

await step('08 no reading at all: calm unavailable state with the real error code', async () => {
  await toIdle()
  mock.configure({ reset: true, telemetry: { kind: 'error', status: 503, code: 'octave_unavailable', message: 'OCTAVE unavailable' } })
  await t('scan-button').click()
  await mode('unavailable', 6000)
  assert((await text('system-error')).includes('octave_unavailable'), 'shows the error code')
  await until(async () => (await count('callout-rpm')) === 0, 2500, 'the old readings to leave')
  assert((await count('provenance-text')) === 0, 'no provenance line without a reading')
  await sleep(1500)
  await shot(10, 'unavailable')
})

await step('09 chat without tools stays a conversation: no summary line, nothing projected', async () => {
  await toIdle()
  mock.configure({ reset: true, chat: { kind: 'no-tools' } })
  const n = await count('message-assistant')
  await send('O que é troca de óleo?')
  await until(async () => (await count('message-assistant')) > n, 10000, 'the answer')
  const last = t('message-assistant').last()
  assert((await last.locator('[data-testid=message-summary]').count()) === 0, 'no "consultou" line')
  await last.locator('[data-testid=message-info]').click()
  assert(((await last.locator('[data-testid=message-info-popover]').textContent()) ?? '').includes('Só conversa'), 'the details say it only talked')
  await sleep(800)
  assert((await count('callout-rpm')) === 0, 'nothing projected on the car')
  assert((await coreState()) !== 'scanning', 'core is not scanning')
})

await step('10 chat errors: service_busy tells when to retry, model_unavailable shows in the indicator', async () => {
  mock.configure({ reset: true, chat: { kind: 'error', status: 429, code: 'service_busy' } })
  await send('Qual a rotação?')
  await t('message-error').first().waitFor({ timeout: 8000 })
  assert((await t('message-error').last().textContent()).includes('10 s'), 'retry hint from Retry-After')
  mock.configure({ chat: { kind: 'error', status: 503, code: 'model_unavailable' } })
  await send('Qual a velocidade?')
  await until(async () => (await count('message-error')) >= 2, 8000, 'the second error')
  assert((await attr('status-cluster', 'data-ollama')) === 'offline', 'Ollama inferred offline')
  assert((await text('status-cluster')).includes('Modelo indisponível'), 'the one sentence says so')
  await sleep(500)
  await shot(11, 'chat-error')
})

await step('11 no page errors, no CSP violations, no request left the origin', async () => {
  // Chromium logs every non-2xx response as a console error ("Failed to load resource"). Steps 08 and 10 provoke 503 and
  // 429 on purpose, so that network noise is ignored; script errors, CSP refusals and anything else still fail the run.
  const real = consoleErrors.filter((m) => !m.startsWith('Failed to load resource: the server responded with a status of'))
  assert(real.length === 0, `console errors: ${real.slice(0, 3).join(' | ')}`)
  assert(!consoleErrors.some((m) => /Content Security Policy|Refused to/i.test(m)), 'a CSP violation was reported')
  assert(foreign.length === 0, `foreign requests: ${foreign.slice(0, 3).join(', ')}`)
  const csp = await page.locator('meta[http-equiv="Content-Security-Policy"]').getAttribute('content')
  assert(csp && csp.includes("default-src 'self'") && csp.includes("connect-src 'self'"), 'production CSP present')
})

await step('12 offline: Core down is shown calmly, state is forgotten, input disabled; recovers by itself', async () => {
  mock.configure({ reset: true })
  await mock.close()
  await mode('offline', 16000)
  assert((await coreState()) === 'offline', 'core offline state')
  assert(await t('offline-banner').isVisible(), 'offline notice')
  assert((await attr('status-cluster', 'data-core')) === 'offline', 'indicator says Core offline')
  assert((await text('status-cluster')).includes('Core offline'), 'one sentence')
  assert((await attr('status-cluster', 'data-ollama')) === 'unknown', 'nothing is known about Ollama while the Core is down')
  assert(await t('chat-input').isDisabled(), 'input disabled while offline')
  assert((await count('clear-button')) === 0 && (await count('live-button')) === 0, 'no projection controls while offline')
  await sleep(1200)
  await shot(12, 'offline')
  mock = await startMockCore({ port: MOCK_PORT })
  await mode('idle', 16000)
  assert((await attr('status-cluster', 'data-core')) === 'online', 'Core back online')
  assert(!(await t('chat-input').isDisabled()), 'input enabled again')
  assert((await count('callout-rpm')) === 0, 'the old reading does not come back')
})

await step('13 layouts: 1280x720, stacked 1024x768, 2560x1440, no horizontal overflow', async () => {
  for (const [w, h, name, n] of [[1280, 720, 'laptop', 13], [1024, 768, 'stacked', 14], [2560, 1440, 'wide', 15]]) {
    await page.setViewportSize({ width: w, height: h })
    await sleep(500)
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
    assert(overflow <= 1, `${name}: horizontal overflow of ${overflow}px`)
    await shot(n, name)
  }
  await page.setViewportSize({ width: 1600, height: 900 })
})

await step('14 reduced motion: loads and renders without errors', async () => {
  const c2 = await browser.newContext({ viewport: { width: 1280, height: 720 }, reducedMotion: 'reduce' })
  const p2 = await c2.newPage()
  const errs = []
  p2.on('pageerror', (e) => errs.push(e.message))
  await p2.goto(UI + '/#/hud', { waitUntil: 'domcontentloaded' })
  await until(async () => (await p2.getByTestId('status-cluster').getAttribute('data-core')) === 'online', 10000, 'Core online (reduced motion)')
  assert(errs.length === 0, `page errors: ${errs[0]}`)
  await c2.close()
})

await browser.close()
await cleanup()

const failed = results.filter((r) => !r.ok)
console.log(`\n${results.length - failed.length}/${results.length} steps passed · screenshots in ${path.relative(uiDir, outDir)}${path.sep}\n`)
process.exit(failed.length ? 1 : 0)
