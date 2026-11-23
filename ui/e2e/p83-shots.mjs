// P8.3 real-browser captures of the active screen against the REAL stack (dev server on :5173 proxying the real Core, which talks to
// the real OCTAVE simulator and Ollama). Uses the procedural car so the images can be shared. Output: ui/e2e/out/p83/ (git-ignored).
//   node e2e/p83-shots.mjs [baseUrl]
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright-core'

const here = path.dirname(fileURLToPath(import.meta.url))
const out = path.join(here, 'out', 'p83')
fs.mkdirSync(out, { recursive: true })
const BASE = process.argv[2] || 'http://127.0.0.1:5173'
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

const browser = await chromium.launch({ channel: 'msedge', headless: true })
for (const [w, h] of [[1920, 1080], [1366, 768], [1280, 720], [1024, 600]]) {
  const ctx = await browser.newContext({ viewport: { width: w, height: h }, reducedMotion: 'reduce' })
  const page = await ctx.newPage()
  const errors = []
  page.on('console', (m) => m.type() === 'error' && errors.push(m.text()))
  page.on('pageerror', (e) => errors.push(String(e)))
  await page.goto(`${BASE}/#/active?vehicle=placeholder`, { waitUntil: 'domcontentloaded' })
  await page.getByTestId('telemetry').waitFor()
  await sleep(3500) // the first status, llm status and telemetry reads
  const info = await page.evaluate(() => ({
    ollama: document.querySelector('[data-testid=chip-ollama]')?.textContent,
    octave: document.querySelector('[data-testid=chip-octave]')?.textContent,
    badge: document.querySelector('[data-testid=origin-badge]')?.textContent,
    rows: ['rpm', 'speed', 'coolant'].map((id) => document.querySelector(`[data-testid=reading-${id}]`)?.textContent),
    note: document.querySelector('[data-testid=telemetry-note]')?.textContent,
    // visible text only (display:none and the screen-reader-only spans do not count), the smallest first
    small: [...document.querySelectorAll('header *, [data-testid=telemetry] *')]
      .filter((e) => [...e.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim()) && !/srOnly/.test(e.className) && e.getClientRects().length > 0)
      .map((e) => [parseFloat(getComputedStyle(e).fontSize), e.textContent.trim().slice(0, 28)])
      .sort((x, y) => x[0] - y[0]).slice(0, 3),
    overflow: [document.documentElement.scrollWidth - innerWidth, document.documentElement.scrollHeight - innerHeight],
  }))
  console.log(`${w}x${h}`, JSON.stringify(info), errors.length ? 'ERRORS ' + errors.join(' | ').slice(0, 200) : 'no console errors')
  await page.screenshot({ path: path.join(out, `active-${w}x${h}.png`) })
  await ctx.close()
}
await browser.close()
