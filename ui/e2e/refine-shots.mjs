// Real-browser captures of model C in the active screen, for the visual refinement (before / after). Local only, git-ignored output.
//   node e2e/refine-shots.mjs before   (uses the already running dev server on :5173, or starts its own on :5182)
//   node e2e/refine-shots.mjs refined
import { spawn } from 'node:child_process'
import fs from 'node:fs'
import http from 'node:http'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright-core'
import { startMockCore } from './mock-core.mjs'

const tag = process.argv[2] || 'refined'
const extra = process.argv.slice(3) // optional "name=hash" pairs
const here = path.dirname(fileURLToPath(import.meta.url))
const uiDir = path.resolve(here, '..')
const out = path.resolve(uiDir, '..', 'assets', 'honda-fit-gd', 'out', 'previews')
fs.mkdirSync(out, { recursive: true })
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const waitHttp = (u) => new Promise((res, rej) => { const go = (n) => http.get(u, (r) => (r.resume(), res())).on('error', () => (n <= 0 ? rej(new Error('no answer')) : setTimeout(() => go(n - 1), 250))); go(80) })

const mock = await startMockCore({ port: 8010 })
const vite = path.join(uiDir, 'node_modules', 'vite', 'bin', 'vite.js')
const server = spawn(process.execPath, [vite, '--host', '127.0.0.1', '--port', '5182', '--strictPort'], { cwd: uiDir, stdio: 'ignore', env: { ...process.env, FIT_AI_CORE_URL: 'http://127.0.0.1:8010' } })
const BASE = 'http://127.0.0.1:5182'
await waitHttp(BASE + '/')
const browser = await chromium.launch({ channel: 'msedge', headless: true })

// before: yaw offsets from the old three-quarter view; refined: named camera presets are chosen by the code, so only the view differs
const shots = tag === 'before'
  ? [['front34', '#/active?vehicle=model-c'], ['side', '#/active?vehicle=model-c&yaw=-35.5'], ['front', '#/active?vehicle=model-c&yaw=33']]
  : tag === 'cams'
    ? ['legacy', 'refined', 'high', 'wide'].flatMap((c) => [[`cam-${c}-front34`, `#/active?vehicle=model-c&view=front34&cam=${c}`], [`cam-${c}-front`, `#/active?vehicle=model-c&view=front&cam=${c}`]])
    : tag === 'grey'
    ? [['front', '#/active?vehicle=model-c&view=front&look=grey'], ['front34', '#/active?vehicle=model-c&view=front34&look=grey']]
    : tag === 'split'
    ? [['front34', '#/active?vehicle=model-c&view=front34&look=split'], ['front', '#/active?vehicle=model-c&view=front&look=split'], ['side', '#/active?vehicle=model-c&view=side&look=split']]
    : [['front34', '#/active?vehicle=model-c&view=front34'], ['side', '#/active?vehicle=model-c&view=side'], ['front', '#/active?vehicle=model-c&view=front'], ...extra.map((e) => e.split('='))]
for (const [name, hash] of shots) {
  const ctx = await browser.newContext({ viewport: { width: 1920, height: 1080 }, reducedMotion: 'reduce' })
  const page = await ctx.newPage()
  const errors = []
  page.on('console', (m) => m.type() === 'error' && errors.push(m.text()))
  await page.goto(`${BASE}/${hash}`, { waitUntil: 'domcontentloaded' })
  await page.getByTestId('vehicle-canvas').waitFor()
  const t0 = Date.now()
  for (;;) {
    const s = await page.getByTestId('vehicle-canvas').evaluate((c) => c.dataset.modelState)
    if (s === 'loaded' || Date.now() - t0 > 40000) break
    await sleep(250)
  }
  await sleep(2500)
  const d = await page.getByTestId('vehicle-canvas').evaluate((c) => ({ ...c.dataset }))
  console.log(`  exterior/interior triangles ${d.exteriorTris}/${d.interiorTris}, visibility pass ${d.visibilityMs} ms, calls ${d.calls}`)
  const file = path.join(out, `model-c-${tag}-${name}.png`)
  await page.screenshot({ path: file })
  console.log(`${tag}/${name}: ${file}${errors.length ? '  ERRORS: ' + errors.join(' | ').slice(0, 200) : ''}`)
  await ctx.close()
}
await browser.close()
server.kill()
await mock.close()
