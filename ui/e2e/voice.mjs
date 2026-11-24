// P9.1 end-to-end: push-to-talk on the real Active screen, real Core, real local STT engine, in headless Edge.
//
// NO REAL MICROPHONE IS OPENED. Chromium's fake capture device plays a SYNTHETIC speech file (the Microsoft Maria pt-BR voice, made
// offline) as if it were the microphone, and auto-accepts the permission prompt. This proves the plumbing end to end (permission,
// capture, resampling, WAV, upload, transcription, state changes, release of the tracks); it is NOT a measure of accuracy on a human voice.
//
//   FIT_E2E_SPEECH_WAV=<16-bit PCM wav, ideally 3-6 s of speech>  node e2e/voice.mjs [baseUrl]
//   (needs the stack: Core on :8000 with the STT model installed, UI dev server on :5173)
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright-core'

const BASE = process.argv[2] || 'http://127.0.0.1:5173'
const SPEECH = process.env.FIT_E2E_SPEECH_WAV
if (!SPEECH || !fs.existsSync(SPEECH)) {
  console.log('SKIP  set FIT_E2E_SPEECH_WAV to a speech WAV (synthetic is fine) to run the voice end-to-end test')
  process.exit(0)
}
const here = path.dirname(fileURLToPath(import.meta.url))
const out = path.join(here, 'out', 'p91')
fs.mkdirSync(out, { recursive: true })
// an ASCII path: some Chromium builds mishandle non-ASCII paths for the fake capture file
const fake = path.join(os.tmpdir(), 'fit-voice-e2e.wav')
fs.copyFileSync(SPEECH, fake)
const wavSeconds = (fs.statSync(fake).size - 44) / 32000
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

let failed = 0
const check = (name, ok, detail = '') => {
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${ok || !detail ? '' : ': ' + detail}`)
  if (!ok) failed++
}
const info = (s) => console.log(`INFO  ${s}`)

const browser = await chromium.launch({
  channel: 'msedge',
  headless: true,
  args: ['--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream', `--use-file-for-fake-audio-capture=${fake}%noloop`],
})

const INIT = () => {
  // observe (never alter) what the page does with the microphone
  window.__mic = { calls: 0, constraints: null, streams: [] }
  const md = navigator.mediaDevices
  const orig = md.getUserMedia.bind(md)
  md.getUserMedia = async (c) => {
    window.__mic.calls++
    window.__mic.constraints = c
    const s = await orig(c)
    window.__mic.streams.push(s)
    return s
  }
  window.__live = () => window.__mic.streams.flatMap((s) => s.getTracks()).filter((t) => t.readyState === 'live').length
}

async function openActive(w, h) {
  const ctx = await browser.newContext({ viewport: { width: w, height: h }, reducedMotion: 'reduce', permissions: ['microphone'] })
  const page = await ctx.newPage()
  const requests = []
  const errors = []
  page.on('request', (r) => {
    const u = new URL(r.url())
    if (u.origin === new URL(BASE).origin && (u.pathname.startsWith('/api') || u.pathname === '/health')) {
      requests.push({ method: r.method(), path: u.pathname, type: r.headers()['content-type'] ?? null, bytes: r.postDataBuffer()?.length ?? 0 })
    }
  })
  page.on('pageerror', (e) => errors.push(String(e)))
  page.on('console', (m) => m.type() === 'error' && !/WebGL|GPU stall|ReadPixels/.test(m.text()) && errors.push(m.text()))
  await page.addInitScript(INIT)
  await page.goto(`${BASE}/#/active?vehicle=placeholder`, { waitUntil: 'domcontentloaded' })
  await page.getByTestId('voice-control').waitFor({ timeout: 15000 })
  await page.waitForFunction(() => document.querySelector('[data-testid=voice-status]')?.getAttribute('data-phase') === 'idle')
  return { ctx, page, requests, errors }
}

const phase = (page) => page.getByTestId('voice-status').getAttribute('data-phase')
const screenState = (page) => page.getByTestId('active-screen').getAttribute('data-state')
const waitPhase = (page, p, timeout = 20000) => page.waitForFunction((x) => document.querySelector('[data-testid=voice-status]')?.getAttribute('data-phase') === x, p, { timeout })
const bars = (page) => page.evaluate(() => Array.from(document.querySelectorAll('[data-testid=voice-waveform] span')).map((b) => b.style.transform))
async function centre(page) {
  const b = await page.getByTestId('voice-control').boundingBox()
  return { x: b.x + b.width / 2, y: b.y + b.height / 2, w: b.width, h: b.height }
}

for (const [w, h] of [[1920, 1080], [1366, 768], [1024, 600]]) {
  console.log(`\n=== ${w}x${h}`)
  const { ctx, page, requests, errors } = await openActive(w, h)
  const tag = `${w}x${h}`

  // 1) at rest: the microphone is closed and nothing reacts
  check(`${tag} idle: microphone never requested before a gesture`, (await page.evaluate(() => window.__mic.calls)) === 0)
  check(`${tag} idle: screen is "active", not "listening"`, (await screenState(page)) === 'active')
  check(`${tag} idle: bars have no inline microphone heights`, (await bars(page)).every((t) => t === ''))
  const c = await centre(page)
  check(`${tag} control is a real touch target (>= 44 px)`, c.w >= 44 && c.h >= 44, `${Math.round(c.w)}x${Math.round(c.h)}`)

  // 2) hold the control while the (fake) device plays the phrase
  const t0 = Date.now()
  await page.mouse.move(c.x, c.y)
  await page.mouse.down()
  await waitPhase(page, 'listening')
  info(`${tag} press -> listening: ${Date.now() - t0} ms (permission auto-accepted by the test flag; a real prompt adds user time)`)
  check(`${tag} listening: the screen state is "listening"`, (await screenState(page)) === 'listening')
  check(`${tag} listening: audio-only constraints`, await page.evaluate(() => window.__mic.constraints?.video === false && !!window.__mic.constraints?.audio))
  check(`${tag} listening: one stream, live`, (await page.evaluate(() => window.__mic.calls)) === 1 && (await page.evaluate(() => window.__live())) === 1)
  check(`${tag} listening: "microphone active" is shown`, /microfone ativo/i.test((await page.getByTestId('voice-status').textContent()) ?? ''))
  const samples = []
  for (let i = 0; i < 6; i++) {
    await sleep(350)
    samples.push((await bars(page)).join('|'))
  }
  check(`${tag} listening: the bars move with the real audio level`, new Set(samples).size > 1 && samples.some((s) => s.includes('scaleY')), `${new Set(samples).size} distinct frames`)
  if (w === 1920) await page.screenshot({ path: path.join(out, `listening-${tag}.png`) })
  else await page.screenshot({ path: path.join(out, `listening-${tag}.png`) })
  const holdUntil = t0 + Math.max(wavSeconds * 1000 + 700, 3000)
  await sleep(Math.max(0, holdUntil - Date.now()))

  // 3) let go: the microphone must be OFF before the state becomes "processing"
  const tRelease = Date.now()
  await page.mouse.up()
  await waitPhase(page, 'transcribing', 5000).catch(() => {})
  const liveAtProcessing = await page.evaluate(() => window.__live())
  const phaseNow = await phase(page)
  if (phaseNow === 'transcribing') {
    check(`${tag} processing: the microphone is already released (0 live tracks)`, liveAtProcessing === 0, `${liveAtProcessing} live`)
    check(`${tag} processing: the screen state is "processing"`, (await screenState(page)) === 'processing')
    check(`${tag} processing: bars no longer follow the microphone`, (await bars(page)).every((t) => t === ''))
    await page.screenshot({ path: path.join(out, `processing-${tag}.png`) })
  } else info(`${tag} transcription finished before the processing state could be sampled`)
  await waitPhase(page, 'completed', 60000)
  const total = Date.now() - tRelease
  const text = (await page.getByTestId('voice-transcript').textContent()) ?? ''
  info(`${tag} release -> text: ${total} ms | recognised: ${JSON.stringify(text.replace('DEV · texto reconhecido', '').trim())}`)
  check(`${tag} completed: some text was recognised`, text.replace('DEV · texto reconhecido', '').trim().length > 3)
  check(`${tag} completed: tracks are all ended`, (await page.evaluate(() => window.__live())) === 0)
  await page.screenshot({ path: path.join(out, `completed-${tag}.png`) })

  // 4) what went over the wire
  const posts = requests.filter((r) => r.method === 'POST')
  check(`${tag} exactly one POST, to /api/v1/voice/transcribe, as audio/wav`, posts.length === 1 && posts[0].path === '/api/v1/voice/transcribe' && posts[0].type === 'audio/wav', JSON.stringify(posts))
  check(`${tag} the upload is a bounded 16 kHz WAV`, posts[0] && posts[0].bytes > 44 + 16000 && posts[0].bytes <= 44 + 16000 * 2 * 21, `${posts[0]?.bytes} bytes`)
  check(`${tag} the chat was never called`, !requests.some((r) => r.path.includes('/chat')))
  check(`${tag} only same-origin local requests`, requests.every((r) => r.path.startsWith('/api') || r.path === '/health'))

  // 5) layout
  const overflow = await page.evaluate(() => ({ x: document.documentElement.scrollWidth - innerWidth, y: document.documentElement.scrollHeight - innerHeight }))
  check(`${tag} no overflow`, overflow.x <= 0 && overflow.y <= 0, JSON.stringify(overflow))
  const small = await page.evaluate(() => Array.from(document.querySelectorAll('[data-testid=voice-status], [data-testid=voice-status] *')).filter((e) => e.children.length === 0 && e.textContent.trim()).map((e) => parseFloat(getComputedStyle(e).fontSize)).filter((s) => s < 12))
  check(`${tag} status text is at least 12 px`, small.length === 0, small.join(','))
  check(`${tag} no page or console errors`, errors.length === 0, errors.join(' | '))
  await ctx.close()
}

console.log('\n=== keyboard (Space held), cancel (Escape), focus loss, navigation, leaving the screen')
{
  const { ctx, page, requests } = await openActive(1366, 768)
  await page.getByTestId('voice-control').focus()
  await page.keyboard.down('Space')
  await waitPhase(page, 'listening')
  check('keyboard: Space held starts listening', (await phase(page)) === 'listening')
  await sleep(1500)
  await page.keyboard.up('Space')
  await waitPhase(page, 'completed', 60000).catch(() => {})
  const done = await phase(page)
  check('keyboard: releasing Space sends and finishes (completed, or a clear "no speech" error)', done === 'completed' || done === 'error', done)
  check('keyboard: tracks released', (await page.evaluate(() => window.__live())) === 0)

  // Escape while listening: nothing is sent
  const before = requests.filter((r) => r.method === 'POST').length
  await page.getByTestId('voice-control').focus()
  await page.keyboard.down('Space')
  await waitPhase(page, 'listening')
  await sleep(500)
  await page.keyboard.press('Escape')
  await page.keyboard.up('Space')
  await waitPhase(page, 'cancelled', 5000)
  check('Escape: capture cancelled', (await phase(page)) === 'cancelled')
  check('Escape: tracks released at once', (await page.evaluate(() => window.__live())) === 0)
  check('Escape: the audio was NOT sent', requests.filter((r) => r.method === 'POST').length === before)

  // click-to-start / click-to-stop (the accessible alternative)
  await sleep(2000)
  const c = await centre(page)
  await page.mouse.click(c.x, c.y) // a quick tap: starts and keeps listening
  await waitPhase(page, 'listening')
  await sleep(1200)
  check('tap: stays listening after a quick tap', (await phase(page)) === 'listening')
  await page.mouse.click(c.x, c.y) // the second tap stops
  await waitPhase(page, 'transcribing', 5000).catch(() => {})
  await waitPhase(page, 'completed', 60000).catch(() => waitPhase(page, 'error', 5000))
  check('tap: the second tap stops and the tracks are released', (await page.evaluate(() => window.__live())) === 0)

  // losing the page (hash navigation) while listening
  await sleep(2000)
  await page.mouse.move(c.x, c.y)
  await page.mouse.down()
  await waitPhase(page, 'listening')
  const sent = requests.filter((r) => r.method === 'POST').length
  await page.evaluate(() => (location.hash = '#/active?vehicle=placeholder&x=1'))
  await sleep(300)
  check('navigation: the capture is cancelled and the tracks released', (await phase(page)) === 'cancelled' && (await page.evaluate(() => window.__live())) === 0)
  await page.mouse.up()
  check('navigation: nothing was sent', requests.filter((r) => r.method === 'POST').length === sent)
  await ctx.close()
}

console.log('\n=== Standby never touches the microphone')
{
  const ctx = await browser.newContext({ viewport: { width: 1366, height: 768 }, permissions: ['microphone'] })
  const page = await ctx.newPage()
  const reqs = []
  page.on('request', (r) => new URL(r.url()).pathname.startsWith('/api') && reqs.push(r.url()))
  await page.addInitScript(INIT)
  await page.goto(`${BASE}/#/`, { waitUntil: 'domcontentloaded' })
  await page.getByTestId('wake').waitFor()
  await sleep(2500)
  check('standby: no microphone request', (await page.evaluate(() => window.__mic.calls)) === 0)
  check('standby: no API request at all', reqs.length === 0, reqs.join(','))
  await ctx.close()
}

await browser.close()
console.log(failed ? `\n${failed} check(s) FAILED` : '\nall passed')
process.exit(failed ? 1 : 0)
