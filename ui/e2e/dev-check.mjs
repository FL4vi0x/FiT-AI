// Is the 3D car shown by the DEV server (React StrictMode mounts effects twice)?   node e2e/dev-check.mjs [url]
import { chromium } from 'playwright-core'
const url = process.argv[2] || 'http://127.0.0.1:5173/#/active'
const b = await chromium.launch({ channel: 'msedge', headless: true })
const page = await (await b.newContext({ viewport: { width: 1366, height: 768 } })).newPage()
const logs = []
page.on('console', (m) => ['error', 'warning'].includes(m.type()) && logs.push(m.type() + ': ' + m.text().slice(0, 200)))
page.on('pageerror', (e) => logs.push('pageerror: ' + e))
await page.goto(url, { waitUntil: 'domcontentloaded' })
await new Promise((r) => setTimeout(r, 5000))
console.log('notice:', await page.getByTestId('vehicle-notice').count(), '| status:', await page.getByTestId('vehicle-stage').getAttribute('data-status'))
console.log(logs.join('\n') || 'no console output')
await b.close()
