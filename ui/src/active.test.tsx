import { act, cleanup, render, renderHook, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { FitAiApi } from './api/client'
import { ActiveHeader, NAV } from './components/active/ActiveHeader'
import { ACTIVATION_END } from './motion/activeTimeline'
import Root, { routeFromHash, wantsDemo } from './Root'
import ActiveScreen from './screens/ActiveScreen/ActiveScreen'
import Experience from './screens/Experience'
import { INITIAL_STATUS, useServiceStatus, type ServiceStatus } from './state/useServiceStatus'
import { useVisualState, VISUAL_STATES } from './state/visualState'

function mockMatchMedia(reduced: boolean) {
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: reduced && query.includes('prefers-reduced-motion'),
    media: query,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
    onchange: null,
  })) as unknown as typeof window.matchMedia
}

// the only things the active screen may ask the Core for on its own: four read-only GETs. NEVER the chat.
const READ_ONLY = ['/health', '/api/v1/vehicle/status', '/api/v1/llm/status', '/api/v1/vehicle/telemetry', '/api/v1/voice/status']

const online: ServiceStatus = { core: 'online', octave: 'connected', simulated: true, ollama: 'unverified' }
const offline: ServiceStatus = { core: 'offline', octave: 'no_core', simulated: null, ollama: 'unverified' }

afterEach(() => {
  cleanup()
  vi.useRealTimers()
  vi.unstubAllGlobals()
  window.location.hash = ''
})

describe('ActiveHeader', () => {
  beforeEach(() => mockMatchMedia(false))

  it('shows the brand, the five sections, the services and a clock', () => {
    render(<ActiveHeader services={online} now={Date.UTC(2026, 10, 22, 16, 47)} />)
    expect(screen.getByRole('img', { name: 'Fit AI' })).toBeInTheDocument()
    expect(screen.getByText('VEHICLE INTELLIGENCE SYSTEM')).toBeInTheDocument()
    expect(screen.getByText('Honda Fit GD (2005)')).toBeInTheDocument()
    expect(screen.getAllByRole('button')).toHaveLength(NAV.length)
    expect(screen.getByTestId('chip-octave')).toHaveTextContent('Conectado')
    expect(screen.getByRole('navigation', { name: 'Seções' })).toBeInTheDocument()
    expect(document.querySelector('time')).not.toBeNull()
  })

  it('has no fake navigation: only Home is current and enabled, the rest is disabled and says "em breve"', () => {
    render(<ActiveHeader services={online} now={0} />)
    expect(screen.getByTestId('nav-home')).toHaveAttribute('aria-current', 'page')
    expect(screen.getByTestId('nav-home')).toBeEnabled()
    for (const id of ['telemetry', 'maintenance', 'history', 'settings']) {
      const b = screen.getByTestId(`nav-${id}`)
      expect(b).toBeDisabled()
      expect(b).toHaveTextContent('em breve')
    }
  })

  it('never shows a service as online when it is not: no Core, Ollama unverified', () => {
    render(<ActiveHeader services={offline} now={0} />)
    expect(screen.getByTestId('system-line')).toHaveTextContent('Sistema desconectado')
    expect(screen.getByTestId('chip-octave')).toHaveTextContent('Sem Core')
    expect(screen.getByTestId('chip-octave')).not.toHaveTextContent('Conectado')
    expect(screen.getByTestId('chip-ollama')).toHaveTextContent('Não verificado')
    expect(screen.queryByText(/^Online$/)).toBeNull()
  })

  it('tells a partial link apart (Core up, vehicle link down)', () => {
    render(<ActiveHeader services={{ ...online, octave: 'vehicle_link_down' }} now={0} />)
    expect(screen.getByTestId('system-line')).toHaveTextContent('Sistema parcial')
    expect(screen.getByTestId('chip-octave')).toHaveTextContent('Sem veículo')
  })
})

describe('ActiveScreen', () => {
  beforeEach(() => mockMatchMedia(false))

  it('is voice-first: no text field, no chat, no bubbles, no invented telemetry', () => {
    const { container } = render(<ActiveScreen state="active" services={online} />)
    expect(container.querySelectorAll('input, textarea, select, form')).toHaveLength(0)
    expect(screen.queryByRole('textbox')).toBeNull()
    expect(screen.queryByText(/rpm|km\/h|°C|chat|mensagem|digite/i)).toBeNull()
    expect(screen.getByTestId('voice-waveform')).toBeInTheDocument()
    expect(screen.getByTestId('ai-core')).toBeInTheDocument()
  })

  it('exposes one landmark; decorative layers are hidden from assistive technology', () => {
    render(<ActiveScreen state="active" services={online} />)
    expect(screen.getAllByRole('main')).toHaveLength(1)
    for (const id of ['ambient-rings', 'vehicle-platform', 'ai-core', 'voice-waveform']) expect(screen.getByTestId(id)).toHaveAttribute('aria-hidden', 'true')
  })

  it.each(VISUAL_STATES.filter((s) => s !== 'standby'))('renders the %s state', (s) => {
    render(<ActiveScreen state={s} services={online} />)
    expect(screen.getByTestId('active-screen')).toHaveAttribute('data-state', s)
  })

  it('without WebGL (jsdom) the 3D area degrades to an accessible notice and the HUD stays', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    render(<ActiveScreen state="active" services={online} />)
    // the 3D module is a lazy chunk: give its first import a realistic time in jsdom
    expect(await screen.findByTestId('vehicle-notice', {}, { timeout: 10_000 })).toHaveTextContent('não está disponível')
    expect(screen.getByTestId('active-header')).toBeInTheDocument()
    expect(screen.getByTestId('ai-core')).toBeInTheDocument()
  })

  it('marks the model as provisional in development, never as the Honda Fit GD', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    render(<ActiveScreen state="active" services={online} />)
    // the badge lives in a development-only lazy module
    expect(await screen.findByTestId('dev-badge', {}, { timeout: 10_000 })).toHaveTextContent(/provisório/i)
    expect(screen.getByTestId('dev-badge')).toHaveTextContent(/não é o Honda Fit GD/i)
  })
})

describe('useVisualState', () => {
  beforeEach(() => vi.useFakeTimers())

  it('standby -> activating -> active on the timeline, and leaves no timer behind', () => {
    const { result, unmount } = renderHook(() => useVisualState({ reduced: false }))
    expect(result.current.state).toBe('standby')
    act(() => result.current.activate())
    expect(result.current.state).toBe('activating')
    act(() => void vi.advanceTimersByTime(ACTIVATION_END - 1))
    expect(result.current.state).toBe('activating')
    act(() => void vi.advanceTimersByTime(1))
    expect(result.current.state).toBe('active')
    unmount()
    expect(vi.getTimerCount()).toBe(0)
  })

  it('reduced motion goes straight to active, without timers', () => {
    const { result } = renderHook(() => useVisualState({ reduced: true }))
    act(() => result.current.activate())
    expect(result.current.state).toBe('active')
    expect(vi.getTimerCount()).toBe(0)
  })

  it('a second activation while activating is ignored (the sequence is not restarted)', () => {
    const { result } = renderHook(() => useVisualState({ reduced: false }))
    act(() => result.current.activate())
    act(() => void vi.advanceTimersByTime(1000))
    act(() => result.current.activate())
    act(() => void vi.advanceTimersByTime(ACTIVATION_END - 1000))
    expect(result.current.state).toBe('active')
  })

  it('unmounting mid-activation clears the timer', () => {
    const { result, unmount } = renderHook(() => useVisualState({ reduced: false }))
    act(() => result.current.activate())
    unmount()
    expect(vi.getTimerCount()).toBe(0)
  })

  it('the demo can jump to the prepared states, and the product never does by itself', () => {
    const { result } = renderHook(() => useVisualState({ reduced: false }))
    act(() => void vi.advanceTimersByTime(60_000))
    expect(result.current.state).toBe('standby')
    for (const s of ['listening', 'processing', 'responding'] as const) {
      act(() => result.current.demoSet(s))
      expect(result.current.state).toBe(s)
    }
  })
})

describe('useServiceStatus', () => {
  const api = (over: Partial<FitAiApi> = {}): FitAiApi => ({
    health: vi.fn().mockResolvedValue({ status: 'ok', service: 'fit-ai', version: '0' }),
    status: vi.fn().mockResolvedValue({ available: true, state: 'connected', source: 'octave', simulated: true, protocol_version: 3, octave_version: '0.9.6', detail: null }),
    telemetry: vi.fn(),
    llmStatus: vi.fn().mockResolvedValue({ state: 'available', model: 'm:t', checked_at: '2026-11-23T00:00:00Z' }),
    voiceStatus: vi.fn().mockResolvedValue({ state: 'available', language: 'pt', max_audio_s: 30, sample_rate: 16000, hint: null }),
    transcribe: vi.fn(),
    chat: vi.fn(),
    ...over,
  })

  it('does nothing while disabled (Standby)', () => {
    const a = api()
    renderHook(() => useServiceStatus(false, a))
    expect(a.health).not.toHaveBeenCalled()
    expect(a.status).not.toHaveBeenCalled()
  })

  it('reports a connected, simulated vehicle link; never touches telemetry or chat', async () => {
    const a = api()
    const { result } = renderHook(() => useServiceStatus(true, a))
    await waitFor(() => expect(result.current.octave).toBe('connected'))
    expect(result.current).toMatchObject({ core: 'online', simulated: true, ollama: 'available' })
    expect(a.telemetry).not.toHaveBeenCalled()
    expect(a.chat).not.toHaveBeenCalled()
  })

  it('Core down -> offline, OCTAVE "no_core" (never online)', async () => {
    const a = api({ health: vi.fn().mockRejectedValue(new Error('down')) })
    const { result } = renderHook(() => useServiceStatus(true, a))
    await waitFor(() => expect(result.current.core).toBe('offline'))
    expect(result.current.octave).toBe('no_core')
    expect(a.status).not.toHaveBeenCalled()
  })

  it('OCTAVE off with the Core up -> unavailable; vehicle link down is its own state', async () => {
    const a = api({ status: vi.fn().mockResolvedValue({ available: false, state: 'octave_unavailable', source: 'octave', simulated: null, protocol_version: null, octave_version: null, detail: null }) })
    const { result } = renderHook(() => useServiceStatus(true, a))
    await waitFor(() => expect(result.current.octave).toBe('unavailable'))
    expect(result.current.core).toBe('online')
    expect(INITIAL_STATUS.ollama).toBe('checking')
  })
})

describe('Experience (Standby -> Active)', () => {
  const fetched: string[] = []
  beforeEach(() => {
    fetched.length = 0
    mockMatchMedia(false)
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        fetched.push(String(input))
        return new Response(JSON.stringify({ status: 'ok', service: 'fit-ai', version: '0', available: true, state: 'connected', source: 'octave', simulated: true }), { status: 200, headers: { 'content-type': 'application/json' } })
      }),
    )
    vi.spyOn(console, 'error').mockImplementation(() => {})
  })

  it('opens on Standby, makes no request, and does not activate by itself', async () => {
    vi.useFakeTimers()
    render(<Experience />)
    await act(async () => void vi.advanceTimersByTime(30_000))
    expect(screen.getByTestId('standby-screen')).toBeInTheDocument()
    expect(screen.queryByTestId('active-screen')).toBeNull()
    expect(fetched).toHaveLength(0)
  })

  it('the wake control starts the activation; the active screen makes only read-only GETs and never the chat', async () => {
    const user = userEvent.setup()
    render(<Experience />)
    await user.click(screen.getByTestId('wake'))
    expect(await screen.findByTestId('active-screen')).toHaveAttribute('data-state', 'activating')
    await waitFor(() => expect(fetched.length).toBeGreaterThanOrEqual(2))
    expect(fetched.every((u) => READ_ONLY.some((p) => u.endsWith(p)))).toBe(true)
    expect(fetched.some((u) => u.includes('chat'))).toBe(false)
    expect(fetched.some((u) => u.endsWith('/api/v1/vehicle/telemetry'))).toBe(true) // the readout asks for the readings, read-only
    await waitFor(() => expect(screen.getByTestId('active-screen')).toHaveAttribute('data-state', 'active'), { timeout: 5000 })
  })

  it('reduced motion: active at once, Standby gone', async () => {
    mockMatchMedia(true)
    const user = userEvent.setup()
    render(<Experience />)
    await user.click(screen.getByTestId('wake'))
    expect(screen.getByTestId('active-screen')).toHaveAttribute('data-state', 'active')
    expect(screen.getByTestId('active-screen')).toHaveAttribute('data-motion', 'reduced')
    await waitFor(() => expect(screen.queryByTestId('standby-layer')).toBeNull())
  })

  it('the development demo panel only exists when asked for', () => {
    const { unmount } = render(<Experience />)
    expect(screen.queryByTestId('demo-panel')).toBeNull()
    unmount()
    render(<Experience demo />)
    expect(screen.getByTestId('demo-panel')).toBeInTheDocument()
  })
})

describe('Root routing', () => {
  beforeEach(() => mockMatchMedia(false))
  it('maps the hashes', () => {
    expect(routeFromHash('')).toBe('standby')
    expect(routeFromHash('#/active')).toBe('active')
    expect(routeFromHash('#/active?demo')).toBe('active')
    expect(routeFromHash('#/hud')).toBe('hud')
    expect(wantsDemo('#/active?demo')).toBe(true)
    expect(wantsDemo('#/active')).toBe(false)
  })

  it('#/active opens the active screen straight away', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('{}', { status: 200 })))
    vi.spyOn(console, 'error').mockImplementation(() => {})
    window.location.hash = '#/active'
    render(<Root />)
    expect(await screen.findByTestId('active-screen')).toBeInTheDocument()
  })
})


describe('the Ollama chip shows the real state', () => {
  beforeEach(() => mockMatchMedia(false))

  it.each([
    ['available', 'Disponível'],
    ['model_not_installed', 'Modelo ausente'],
    ['unavailable', 'Desligado'],
    ['unverified', 'Não verificado'],
    ['not_configured', 'Sem modelo'],
    ['checking', 'Verificando'],
  ] as const)('%s -> "%s"', (ollama, text) => {
    render(<ActiveHeader services={{ ...online, ollama }} now={0} />)
    expect(screen.getByTestId('chip-ollama')).toHaveTextContent(text)
  })

  it('is never "Disponível" unless the Core said so', () => {
    for (const ollama of ['unverified', 'unavailable', 'checking', 'not_configured', 'model_not_installed'] as const) {
      const { unmount } = render(<ActiveHeader services={{ ...online, ollama }} now={0} />)
      expect(screen.getByTestId('chip-ollama')).not.toHaveTextContent('Disponível')
      unmount()
    }
  })
})

describe('useServiceStatus and the language-model check', () => {
  const base = (llm: unknown): FitAiApi => ({
    health: vi.fn().mockResolvedValue({ status: 'ok', service: 'fit-ai', version: '0' }),
    status: vi.fn().mockResolvedValue({ available: true, state: 'connected', source: 'octave', simulated: true, protocol_version: 3, octave_version: '0.9.6', detail: null }),
    telemetry: vi.fn(),
    llmStatus: llm as FitAiApi['llmStatus'],
    voiceStatus: vi.fn().mockResolvedValue({ state: 'available', language: 'pt', max_audio_s: 30, sample_rate: 16000, hint: null }),
    transcribe: vi.fn(),
    chat: vi.fn(),
  })

  it('reports each state the Core sends', async () => {
    for (const state of ['available', 'model_not_installed', 'unavailable', 'unverified', 'not_configured'] as const) {
      const { result, unmount } = renderHook(() => useServiceStatus(true, base(vi.fn().mockResolvedValue({ state, model: 'm:t', checked_at: 'x' }))))
      await waitFor(() => expect(result.current.octave).toBe('connected'))
      expect(result.current.ollama).toBe(state)
      unmount()
    }
  })

  it('an unknown state, a malformed body or a failing endpoint is "unverified", and the vehicle link still shows', async () => {
    for (const llm of [vi.fn().mockResolvedValue({ state: 'connected' }), vi.fn().mockResolvedValue({}), vi.fn().mockResolvedValue(null), vi.fn().mockRejectedValue(new Error('404'))]) {
      const { result, unmount } = renderHook(() => useServiceStatus(true, base(llm)))
      await waitFor(() => expect(result.current.octave).toBe('connected'))
      expect(result.current.ollama).toBe('unverified')
      unmount()
    }
  })

  it('Core down -> Ollama "unverified" (not asked), never "available"', async () => {
    const a = base(vi.fn())
    a.health = vi.fn().mockRejectedValue(new Error('down'))
    const { result } = renderHook(() => useServiceStatus(true, a))
    await waitFor(() => expect(result.current.core).toBe('offline'))
    expect(result.current.ollama).toBe('unverified')
    expect(a.llmStatus).not.toHaveBeenCalled()
  })

  it('never calls chat or telemetry', async () => {
    const a = base(vi.fn().mockResolvedValue({ state: 'available', model: 'm:t', checked_at: 'x' }))
    const { result } = renderHook(() => useServiceStatus(true, a))
    await waitFor(() => expect(result.current.ollama).toBe('available'))
    expect(a.chat).not.toHaveBeenCalled()
    expect(a.telemetry).not.toHaveBeenCalled()
  })
})
