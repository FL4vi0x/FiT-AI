import { act, cleanup, render, screen, waitFor, fireEvent } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ensurePointerEvent, FakeMic } from './testkit'

// everything is real (Experience, the hook, the machine, the screen, the bars, the requests) except the browser microphone itself
const mic = new FakeMic()
vi.mock('./capture', async (original) => ({ ...(await original<typeof import('./capture')>()), createBrowserMic: () => mic }))

const { default: Experience } = await import('../screens/Experience')

function mockMatchMedia(reduced: boolean) {
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: reduced && query.includes('prefers-reduced-motion'), media: query, addEventListener: vi.fn(), removeEventListener: vi.fn(),
    addListener: vi.fn(), removeListener: vi.fn(), dispatchEvent: vi.fn(), onchange: null,
  })) as unknown as typeof window.matchMedia
}

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } })
const calls: { url: string; method: string; type: string | null; bodyBytes: number }[] = []
let coreUp = true
let answer: () => Response

beforeEach(() => {
  calls.length = 0
  coreUp = true
  answer = () => json({ text: 'qual é a velocidade do carro?', silent: false, duration_s: 1, processing_ms: 700, language: 'pt', model: 'faster-whisper-small' })
  mockMatchMedia(true) // active at once
  ensurePointerEvent()
  Object.assign(mic, { opens: 0, sessions: [], rejectWith: null, manual: false })
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const headers = new Headers(init?.headers)
    calls.push({ url, method: init?.method ?? 'GET', type: headers.get('content-type'), bodyBytes: (init?.body as Uint8Array | undefined)?.length ?? 0 })
    if (!coreUp) throw new TypeError('network down')
    if (url.endsWith('/api/v1/voice/transcribe')) return answer()
    if (url.endsWith('/api/v1/voice/status')) return json({ state: 'available', language: 'pt', max_audio_s: 30, sample_rate: 16000, hint: null })
    if (url.endsWith('/api/v1/llm/status')) return json({ state: 'available', model: 'm:t', checked_at: new Date().toISOString() })
    return json({ status: 'ok', service: 'fit-ai', version: '0', available: true, state: 'connected', source: 'octave', simulated: true })
  }))
  vi.spyOn(console, 'error').mockImplementation(() => {})
})
afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  window.location.hash = ''
})

const screenState = () => screen.getByTestId('active-screen').getAttribute('data-state')
const press = () => fireEvent.pointerDown(screen.getByTestId('voice-control'), { button: 0, pointerId: 1 })
const release = () => fireEvent.pointerUp(screen.getByTestId('voice-control'), { button: 0, pointerId: 1 })
const barTransforms = () => Array.from(screen.getByTestId('voice-waveform').querySelectorAll<HTMLElement>('span')).map((b) => b.style.transform)

async function openActive() {
  render(<Experience initial="active" />)
  expect(await screen.findByTestId('voice-control')).toBeInTheDocument()
  await waitFor(() => expect(screen.getByTestId('voice-status')).toHaveAttribute('data-phase', 'idle'))
}

describe('push-to-talk on the active screen', () => {
  it('opens with the microphone closed and the bars NOT reacting to anything', async () => {
    await openActive()
    expect(mic.opens).toBe(0)
    expect(screenState()).toBe('active')
    expect(barTransforms().every((t) => t === '')).toBe(true) // ambient CSS only: no inline "listening" heights
    expect(calls.filter((c) => c.method === 'POST')).toHaveLength(0)
  })

  it('the visual state is "listening" only while the microphone is really open', async () => {
    mic.manual = true
    await openActive()
    press()
    await waitFor(() => expect(screen.getByTestId('voice-status')).toHaveAttribute('data-phase', 'permission_requested'))
    expect(screenState()).toBe('active') // asking permission is not listening
    act(() => void mic.grantNext())
    await waitFor(() => expect(screenState()).toBe('listening'))
    expect(screen.getByTestId('voice-status')).toHaveTextContent(/microfone ativo/i)
  })

  it('the bars follow the real level while listening, and are released as soon as the microphone is off', async () => {
    await openActive()
    press()
    await waitFor(() => expect(screenState()).toBe('listening'))
    act(() => mic.last.level(0.1))
    await waitFor(() => expect(barTransforms().some((t) => t.startsWith('scaleY('))).toBe(true))
    expect(barTransforms()[Math.floor(barTransforms().length / 2)]).toMatch(/scaleY\(0\.[5-9]/) // the centre bar is the loud one

    // hold it for real, then let go: the screen goes to processing and the bars stop reacting
    await new Promise((r) => setTimeout(r, 400))
    release()
    await waitFor(() => expect(screenState()).not.toBe('listening'))
    expect(mic.last.released).toBe(true)
    act(() => mic.last.level(0.9)) // a late block from the closed microphone
    await waitFor(() => expect(barTransforms().every((t) => t === '')).toBe(true))
  })

  it('shows processing while the Core transcribes, and the microphone is already off', async () => {
    let finish!: () => void
    answer = () => json({ text: 'ok', silent: false, duration_s: 1, processing_ms: 1, language: 'pt', model: 'm' })
    const slow = new Promise<void>((r) => (finish = r))
    const original = globalThis.fetch as unknown as (i: RequestInfo | URL, init?: RequestInit) => Promise<Response>
    vi.stubGlobal('fetch', vi.fn(async (i: RequestInfo | URL, init?: RequestInit) => {
      if (String(i).endsWith('/voice/transcribe')) await slow
      return original(i, init)
    }))
    await openActive()
    press()
    await waitFor(() => expect(screenState()).toBe('listening'))
    await new Promise((r) => setTimeout(r, 400))
    release()
    await waitFor(() => expect(screenState()).toBe('processing'))
    expect(mic.last.released).toBe(true)
    expect(screen.getByTestId('voice-status')).toHaveTextContent('Reconhecendo')
    expect(screen.getByTestId('voice-status')).not.toHaveTextContent(/microfone ativo/i)
    finish()
    await waitFor(() => expect(screenState()).toBe('active'))
  })

  it('sends one 16 kHz WAV to /voice/transcribe and NEVER to the chat; the text is shown only in development', async () => {
    await openActive()
    press()
    await waitFor(() => expect(screenState()).toBe('listening'))
    await new Promise((r) => setTimeout(r, 400))
    release()
    await waitFor(() => expect(screen.getByTestId('voice-transcript')).toHaveTextContent('qual é a velocidade do carro?'))
    const posts = calls.filter((c) => c.method === 'POST')
    expect(posts).toHaveLength(1)
    expect(posts[0]).toMatchObject({ url: '/api/v1/voice/transcribe', type: 'audio/wav' })
    expect(posts[0]!.bodyBytes).toBe(44 + 16000 * 2) // 1 s of 16-bit mono at 16 kHz, after resampling from 48 kHz
    expect(calls.some((c) => c.url.includes('/chat'))).toBe(false)
  })

  it('a denied permission is explained, not silent, and sends nothing', async () => {
    mic.rejectWith = Object.assign(new Error('x'), { name: 'NotAllowedError' })
    await openActive()
    press()
    await waitFor(() => expect(screen.getByTestId('voice-detail')).toHaveTextContent(/Permissão do microfone negada/))
    expect(screenState()).toBe('active')
    expect(calls.filter((c) => c.method === 'POST')).toHaveLength(0)
  })

  it('a missing STT model is explained with where to look', async () => {
    answer = () => json({ error: { code: 'stt_model_missing', message: 'x' }, request_id: 'r' }, 503)
    await openActive()
    press()
    await waitFor(() => expect(screenState()).toBe('listening'))
    await new Promise((r) => setTimeout(r, 400))
    release()
    await waitFor(() => expect(screen.getByTestId('voice-detail')).toHaveTextContent('docs/poc-09-01-local-stt.md'))
  })

  it('the Core going down hides the control (the screen is "unavailable") and speech does not start', async () => {
    coreUp = false
    render(<Experience initial="active" />)
    await waitFor(() => expect(screenState()).toBe('unavailable'))
    expect(screen.queryByTestId('voice-control')).toBeNull()
    expect(mic.opens).toBe(0)
  })

  it('leaving the screen while listening releases the microphone', async () => {
    await openActive()
    press()
    await waitFor(() => expect(screenState()).toBe('listening'))
    const s = mic.last
    act(() => void window.dispatchEvent(new HashChangeEvent('hashchange')))
    expect(s.released).toBe(true)
    await waitFor(() => expect(screenState()).toBe('active'))
  })

  it('Standby never touches the microphone nor the speech status', async () => {
    render(<Experience />)
    await new Promise((r) => setTimeout(r, 100))
    expect(mic.opens).toBe(0)
    expect(calls).toHaveLength(0)
  })
})
