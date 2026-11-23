// Idle cost of the Standby in headless Edge (SOFTWARE rasterisation, so pessimistic): main-thread busy fraction over 6 s.
//   npm run build && node e2e/standby-perf.mjs
import { spawn } from 'node:child_process'
import http from 'node:http'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright-core'
const uiDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const UI = 'http://127.0.0.1:4175'
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const waitHttp = (u) => new Promise((res, rej) => { const go = (n) => http.get(u, (r) => (r.resume(), res())).on('error', () => (n <= 0 ? rej(new Error('no answer')) : setTimeout(() => go(n - 1), 250))); go(60) })
const pv = spawn(process.execPath, [path.join(uiDir, 'node_modules', 'vite', 'bin', 'vite.js'), 'preview', '--host', '127.0.0.1', '--port', '4175', '--strictPort'], { cwd: uiDir, stdio: 'ignore' })
await waitHttp(UI + '/')
const b = await chromium.launch({ channel: 'msedge', headless: true })
const page = await (await b.newContext({ viewport: { width: 1920, height: 1080 } })).newPage()
const cdp = await page.context().newCDPSession(page)
await cdp.send('Performance.enable')
const m = async () => Object.fromEntries((await cdp.send('Performance.getMetrics')).metrics.map((x) => [x.name, x.value]))
await page.goto(UI + '/', { waitUntil: 'domcontentloaded' })
let a = await m(); let t0 = Date.now(); await sleep(2600); let e = await m()
console.log(`entrance (0-2.6 s): main thread busy ${(((e.TaskDuration - a.TaskDuration) / ((Date.now() - t0) / 1000)) * 100).toFixed(1)}%`)
await sleep(1000)
a = await m(); t0 = Date.now(); await sleep(6000); e = await m()
console.log(`idle (6 s, loops running): main thread busy ${(((e.TaskDuration - a.TaskDuration) / ((Date.now() - t0) / 1000)) * 100).toFixed(1)}%`)
await b.close(); pv.kill(); process.exit(0)
