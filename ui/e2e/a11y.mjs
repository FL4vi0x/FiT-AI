// Accessibility audit with axe-core (WCAG 2.0/2.1 A and AA + best practices) in headless Edge, against the dev server.
// Screens: Standby, Active (procedural car, so the audit never depends on a local, rights-restricted model), the dev switcher is excluded.
//   node e2e/a11y.mjs [baseUrl]            exit code 1 when a violation of impact serious or critical remains
import fs from 'node:fs'
import path from 'node:path'
import { createRequire } from 'node:module'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright-core'

const require = createRequire(import.meta.url)
const axeSource = fs.readFileSync(require.resolve('axe-core/axe.min.js'), 'utf8')
const BASE = process.argv[2] || 'http://127.0.0.1:5173'
const here = path.dirname(fileURLToPath(import.meta.url))
const out = path.join(here, 'out', 'p83')
fs.mkdirSync(out, { recursive: true })
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

const SCREENS = [
  { name: 'standby', hash: '#/', wait: async (page) => page.getByTestId('wake').waitFor() },
  { name: 'active', hash: '#/active?vehicle=placeholder', wait: async (page) => { await page.getByTestId('telemetry').waitFor(); await sleep(3500) } },
]
const SIZES = [[1920, 1080], [1024, 600]]

const browser = await chromium.launch({ channel: 'msedge', headless: true })
let blocking = 0
const all = []
for (const screen of SCREENS) {
  for (const [w, h] of SIZES) {
    const ctx = await browser.newContext({ viewport: { width: w, height: h }, reducedMotion: 'reduce', bypassCSP: true })
    const page = await ctx.newPage()
    await page.goto(`${BASE}/${screen.hash}`, { waitUntil: 'domcontentloaded' })
    await screen.wait(page)
    await page.evaluate(axeSource)
    const result = await page.evaluate(() =>
      // eslint-disable-next-line no-undef
      axe.run(document, { runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'best-practice'] }, resultTypes: ['violations', 'incomplete'] }),
    )
    const v = result.violations.map((x) => ({ id: x.id, impact: x.impact, nodes: x.nodes.length, help: x.help, targets: x.nodes.slice(0, 3).map((n) => n.target.join(' ')) }))
    const inc = result.incomplete.map((x) => ({ id: x.id, nodes: x.nodes.length }))
    console.log(`\n${screen.name} ${w}x${h}: ${v.length} violation(s), ${inc.length} "needs review"`)
    for (const x of v) console.log(`  [${x.impact}] ${x.id} x${x.nodes}: ${x.help}\n      ${x.targets.join(' | ')}`)
    if (inc.length) console.log('  needs review:', inc.map((i) => `${i.id}(${i.nodes})`).join(', '))
    blocking += v.filter((x) => x.impact === 'serious' || x.impact === 'critical').length
    all.push({ screen: screen.name, size: `${w}x${h}`, violations: v, incomplete: inc })
    await ctx.close()
  }
}
await browser.close()
fs.writeFileSync(path.join(out, 'a11y.json'), JSON.stringify(all, null, 2))
console.log(blocking ? `\n${blocking} serious/critical violation(s)` : '\nno serious or critical violation')
process.exit(blocking ? 1 : 0)
