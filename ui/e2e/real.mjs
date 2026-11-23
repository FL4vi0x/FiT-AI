// The built UI against the REAL stack: OCTAVE (simulation, headless), the Fit AI Core (python -m fit_ai) and, unless
// --no-llm, the portable Ollama. It starts only what it needs, on loopback, with a throw-away data directory, and stops
// only what it started. Windows paths of this repository (runtime\octave, runtime\tools\ollama-*.ps1).
//
//   npm run build && npm run e2e:real            (add --no-llm to skip the chat steps that need the model)
import { spawn, spawnSync } from 'node:child_process'
import fs from 'node:fs'
import http from 'node:http'
import net from 'node:net'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright-core'

const here = path.dirname(fileURLToPath(import.meta.url))
const uiDir = path.resolve(here, '..')
const repo = path.resolve(uiDir, '..')
const runtime = path.resolve(repo, '..', 'runtime')
const outDir = path.join(here, 'out')
fs.mkdirSync(outDir, { recursive: true })
const NO_LLM = process.argv.includes('--no-llm')

const UI_PORT = 4173
const UI = `http://127.0.0.1:${UI_PORT}`
const CORE = 'http://127.0.0.1:8000'
const dataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'fitai-ui-e2e-'))

const results = []
async function step(name, fn) {
  const t0 = Date.now()
  try {
    await fn()
    results.push({ name, ok: true })
    console.log(`  PASS  ${name}  (${((Date.now() - t0) / 1000).toFixed(1)} s)`)
  } catch (e) {
    results.push({ name, ok: false })
    console.log(`  FAIL  ${name}\n        ${String(e?.message ?? e).split('\n')[0]}`)
  }
}
const assert = (c, m) => {
  if (!c) throw new Error(m)
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
async function until(fn, timeout, msg) {
  const end = Date.now() + timeout
  while (Date.now() < end) {
    try {
      if (await fn()) return
    } catch {
      /* keep waiting */
    }
    await sleep(200)
  }
  throw new Error(`timed out waiting for ${msg}`)
}
const portOpen = (port) =>
  new Promise((resolve) => {
    const s = net.connect({ host: '127.0.0.1', port }, () => (s.destroy(), resolve(true)))
    s.on('error', () => resolve(false))
  })
const getJson = (url) =>
  new Promise((resolve, reject) =>
    http
      .get(url, (r) => {
        let b = ''
        r.on('data', (c) => (b += c))
        r.on('end', () => {
          try {
            resolve({ status: r.statusCode, body: JSON.parse(b) })
          } catch {
            resolve({ status: r.statusCode, body: null })
          }
        })
      })
      .on('error', reject),
  )

// ───────── stack lifecycle (only what we start) ─────────
const started = []
const killTree = (p) => p?.pid && spawnSync('taskkill', ['/PID', String(p.pid), '/T', '/F'], { stdio: 'ignore' })
function startOctave() {
  const p = spawn(path.join(runtime, 'octave', 'OCTAVE.exe'), ['--headless', '--sim', '--service', '9876'], { cwd: path.join(runtime, 'octave'), stdio: 'ignore', windowsHide: true })
  started.push(p)
  return p
}
function startCore(allowOrigins) {
  const env = { ...process.env, PYTHONDONTWRITEBYTECODE: '1', FIT_AI_DATA_DIR: dataDir }
  if (allowOrigins) env.FIT_AI_CHAT_ALLOWED_ORIGINS = allowOrigins
  else delete env.FIT_AI_CHAT_ALLOWED_ORIGINS
  const p = spawn(path.join(repo, '.venv', 'Scripts', 'python.exe'), ['-B', '-m', 'fit_ai'], { cwd: repo, env, stdio: 'ignore', windowsHide: true })
  started.push(p)
  return p
}
let llmStarted = false
function startOllama() {
  spawnSync('powershell', ['-NoProfile', '-File', path.join(runtime, 'tools', 'ollama-serve.ps1')], { stdio: 'ignore' })
  llmStarted = true
}
function stopAll() {
  for (const p of started) killTree(p)
  if (llmStarted) spawnSync('powershell', ['-NoProfile', '-File', path.join(runtime, 'tools', 'ollama-stop.ps1')], { stdio: 'ignore' })
  fs.rmSync(dataDir, { recursive: true, force: true })
}
process.on('exit', stopAll)

for (const [port, what] of [[8000, 'Fit AI Core'], [9876, 'OCTAVE'], [UI_PORT, 'UI preview'], ...(NO_LLM ? [] : [[11434, 'Ollama']])]) {
  if (await portOpen(port)) {
    console.error(`port ${port} (${what}) is already in use: stop it first, this script only manages what it starts.`)
    process.exit(2)
  }
}

console.log(`\nFit AI UI · real stack (OCTAVE simulation + Core${NO_LLM ? '' : ' + Ollama'}), data dir ${dataDir}\n`)
const octave = startOctave()
if (!NO_LLM) startOllama()
await until(() => portOpen(9876), 30000, 'OCTAVE on 9876')
let core = startCore(null) // first WITHOUT the browser origin allow-list, on purpose
await until(async () => (await getJson(`${CORE}/health`)).status === 200, 30000, 'the Core')
if (!NO_LLM) await until(() => portOpen(11434), 30000, 'Ollama')

const viteBin = path.join(uiDir, 'node_modules', 'vite', 'bin', 'vite.js')
const preview = spawn(process.execPath, [viteBin, 'preview', '--host', '127.0.0.1', '--port', String(UI_PORT), '--strictPort'], { cwd: uiDir, stdio: 'ignore' })
started.push(preview)
await until(async () => (await getJson(`${UI}/`).catch(() => ({ status: 0 }))).status === 200, 20000, 'the UI preview')

const browser = await chromium.launch({ channel: 'msedge', headless: true })
const ctx = await browser.newContext({ viewport: { width: 1600, height: 900 } })
const page = await ctx.newPage()
const pageErrors = []
page.on('pageerror', (e) => pageErrors.push(e.message))
const t = (id) => page.getByTestId(id)
const count = (id) => t(id).count()
const text = async (id) => (await t(id).first().textContent()) ?? ''
const shot = (name) => page.screenshot({ path: path.join(outDir, `real-${name}.png`) })
const mode = (m, timeout = 15000) => page.locator(`[data-testid=app][data-mode=${m}]`).waitFor({ timeout })
const send = async (q) => {
  await t('chat-input').fill(q)
  await t('chat-input').press('Enter')
}

await step('01 boot against the real Core: CORE online, OCTAVE connected and SIMULATED', async () => {
  await page.goto(UI + '/#/hud', { waitUntil: 'domcontentloaded' })
  await until(async () => (await t('status-cluster').getAttribute('data-core')) === 'online', 15000, 'CORE online')
  await until(async () => (await t('status-cluster').getAttribute('data-octave')) === 'connected', 15000, 'OCTAVE connected')
  assert((await t('status-cluster').getAttribute('data-simulated')) === 'true', 'the source is flagged as simulated')
  const h = await getJson(`${CORE}/health`)
  await t('status-cluster').click()
  assert((await text('status-core')).includes(h.body.version), 'the status details carry the real Core version')
  await page.keyboard.press('Escape')
  await sleep(1500)
  await shot('01-boot')
})

await step('02 scan: the callouts show what the real telemetry endpoint returns', async () => {
  await t('scan-button').click()
  await mode('presenting', 15000)
  await t('callout-rpm').waitFor()
  const rpm = Number((await text('callout-rpm-value')).replace(/\D/g, ''))
  const api = (await getJson(`${CORE}/api/v1/vehicle/telemetry`)).body
  assert(Number.isFinite(rpm), 'rpm is a number')
  assert(Math.abs(rpm - api.rpm) <= 600, `UI rpm ${rpm} should be close to the API's ${api.rpm} (same source, a moment apart)`)
  assert(api.simulated === true && (await text('provenance-text')).startsWith('Simulado'), 'the provenance line says the source is simulated')
  await sleep(1500)
  await shot('02-scan')
})

await step('03 the Core refuses the UI origin until it is allow-listed, and the UI says how to fix it', async () => {
  await t('clear-button').click()
  await mode('idle', 6000)
  await send('Qual a rotação do motor?')
  await t('message-error').first().waitFor({ timeout: 15000 })
  const msg = await text('message-error')
  assert(msg.includes('origin_not_allowed'), `expected origin_not_allowed, got: ${msg}`)
  assert(msg.includes('FIT_AI_CHAT_ALLOWED_ORIGINS'), 'the message names the setting to use')
  await shot('03-origin-refused')
})

// restart the Core with the browser origin allow-listed (the supported way to let the proxied UI call POST /api/v1/chat)
killTree(core)
await until(async () => !(await portOpen(8000)), 15000, 'the Core to stop')
core = startCore(`${UI},http://127.0.0.1:5173`)
await until(async () => (await getJson(`${CORE}/health`).catch(() => ({ status: 0 }))).status === 200, 30000, 'the Core (allow-listed)')
await until(async () => (await t('status-cluster').getAttribute('data-core')) === 'online', 20000, 'the UI to see the Core again')

if (!NO_LLM) {
  await step('04 chat with the real model: tool badge, verification, direct reading projected, Ollama inferred', async () => {
    await mode('idle', 10000).catch(() => {})
    const n = await count('message-assistant')
    await send('Qual a rotação do motor?')
    await mode('thinking', 8000)
    await shot('04a-thinking')
    await until(async () => (await count('message-assistant')) > n, 170000, 'the model answer')
    const bubble = t('message-assistant').last()
    const summary = (await bubble.locator('[data-testid=message-summary]').textContent()) ?? ''
    assert(summary.includes('Consultou a telemetria') && summary.includes('dados simulados'), `the quiet line: ${summary}`)
    await bubble.locator('[data-testid=message-info]').click()
    const info = (await bubble.locator('[data-testid=message-info-popover]').textContent()) ?? ''
    assert(info.includes('conferidos pelo sistema'), 'the details say the numbers were verified')
    assert(/Escrita pelo modelo|Montada pelo sistema/.test(info), `who wrote it: ${info.slice(0, 60)}`)
    await t('callout-rpm').waitFor({ timeout: 15000 })
    const fellBack = (await bubble.locator('[data-testid=note-fallback]').count()) === 1
    assert((await t('status-cluster').getAttribute('data-ollama')) === 'online' || fellBack, 'Ollama inferred from the answer')
    await sleep(1800)
    await shot('04b-answer')
  })

  await step('05 a general question stays a conversation (no tools, nothing projected)', async () => {
    await t('clear-button').click()
    await mode('idle', 6000)
    const n = await count('message-assistant')
    await send('O que é troca de óleo?')
    await until(async () => (await count('message-assistant')) > n, 170000, 'the answer')
    const last = t('message-assistant').last()
    assert((await last.locator('[data-testid=message-summary]').count()) === 0, 'no consulted-the-car line')
    assert((await count('callout-rpm')) === 0, 'nothing projected')
    await shot('05-conversation')
  })
}

await step('06 OCTAVE stops: the UI shows a calm unavailable state with the Core\'s real error code', async () => {
  killTree(octave)
  await until(async () => ['unreachable', 'degraded'].includes(await t('status-cluster').getAttribute('data-octave')), 15000, 'the OCTAVE state to change')
  if (await count('clear-button')) await t('clear-button').click()
  await mode('idle', 6000)
  await t('scan-button').click()
  await mode('unavailable', 15000)
  const err = await text('system-error')
  assert(/octave|vehicle|no_data|timeout/i.test(err), `real error code expected, got: ${err}`)
  assert((await count('callout-rpm')) === 0, 'no invented values')
  await sleep(1500)
  await shot('06-unavailable')
})

await step('07 the Core stops: offline state, input disabled', async () => {
  killTree(core)
  await mode('offline', 20000)
  assert(await t('offline-banner').isVisible(), 'offline banner')
  assert(await t('chat-input').isDisabled(), 'input disabled')
  await sleep(1200)
  await shot('07-offline')
})

await step('08 no page errors in the whole run', async () => {
  assert(pageErrors.length === 0, `page errors: ${pageErrors.slice(0, 2).join(' | ')}`)
})

await browser.close()
stopAll()
const failed = results.filter((r) => !r.ok)
console.log(`\n${results.length - failed.length}/${results.length} steps passed · screenshots in ${path.relative(uiDir, outDir)}${path.sep}real-*.png\n`)
process.exit(failed.length ? 1 : 0)

