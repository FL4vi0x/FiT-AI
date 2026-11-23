import { act, cleanup, render, renderHook, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, NetworkError, type FitAiApi } from './api/client'
import { TelemetryReadout } from './components/active/TelemetryReadout'
import type { ServiceStatus } from './state/useServiceStatus'
import { TELEMETRY_POLL_MS, useTelemetry, type TelemetryView } from './state/useTelemetry'

// P8.3: the telemetry readout shows what the Core provides, labelled, and nothing else.

afterEach(() => {
  cleanup()
  vi.useRealTimers()
})

const online: ServiceStatus = { core: 'online', octave: 'connected', simulated: true, ollama: 'available' }
const T0 = Date.UTC(2026, 10, 23, 12, 0, 0)
const reading = (over: Record<string, unknown> = {}) => ({
  rpm: 820 as number | null,
  speed_kmh: 0 as number | null,
  coolant_temp_c: 90.5 as number | null,
  missing: [] as string[],
  source: 'octave',
  simulated: true as boolean | null,
  timestamp: new Date(T0).toISOString(),
  ...over,
})
const ok = (r = reading()): TelemetryView => ({ kind: 'ok', reading: r, receivedAt: T0 })

describe('TelemetryReadout', () => {
  it('shows RPM, speed and coolant temperature with units, and the simulated badge', () => {
    render(<TelemetryReadout view={ok()} services={online} now={T0 + 1000} />)
    expect(screen.getByTestId('reading-rpm')).toHaveTextContent('820rpm')
    expect(screen.getByTestId('reading-speed')).toHaveTextContent('0km/h')
    expect(screen.getByTestId('reading-coolant')).toHaveTextContent('90,5°C')
    expect(screen.getByTestId('origin-badge')).toHaveTextContent('DADOS SIMULADOS')
    expect(screen.getByTestId('telemetry')).toHaveAttribute('data-origin', 'sim')
    expect(screen.getByTestId('telemetry-note')).toHaveTextContent('Conexão: conectado')
  })

  it('speed 0 is a real zero, a missing value is an em dash (never zero)', () => {
    render(<TelemetryReadout view={ok(reading({ coolant_temp_c: null, missing: ['coolant_temp_c'] }))} services={online} now={T0} />)
    expect(screen.getByTestId('reading-speed')).toHaveTextContent('0km/h')
    expect(screen.getByTestId('reading-coolant')).toHaveTextContent('—')
    expect(screen.getByTestId('reading-coolant')).toHaveAttribute('data-absent')
    expect(screen.getByTestId('reading-coolant')).toHaveTextContent('indisponível')
    expect(screen.getByTestId('telemetry-note')).toHaveTextContent('Leitura parcial')
  })

  it('the origin badge follows the Core: simulated, real, or not stated (never assumed)', () => {
    const cases: Array<[boolean | null, string, string]> = [
      [true, 'DADOS SIMULADOS', 'sim'],
      [false, 'DADOS DO VEÍCULO', 'real'],
      [null, 'ORIGEM NÃO INFORMADA', 'unknown'],
    ]
    for (const [sim, text, tone] of cases) {
      const { unmount } = render(<TelemetryReadout view={ok(reading({ simulated: sim }))} services={online} now={T0} />)
      expect(screen.getByTestId('origin-badge')).toHaveTextContent(text)
      expect(screen.getByTestId('telemetry')).toHaveAttribute('data-origin', tone)
      unmount()
    }
  })

  it('before any reading the badge still says what the source is (from the status check) and no value is shown', () => {
    render(<TelemetryReadout view={{ kind: 'loading' }} services={online} now={T0} />)
    expect(screen.getByTestId('origin-badge')).toHaveTextContent('DADOS SIMULADOS')
    for (const id of ['rpm', 'speed', 'coolant']) expect(screen.getByTestId(`reading-${id}`)).toHaveTextContent('—')
    expect(screen.getByTestId('telemetry-note')).toHaveTextContent('Aguardando')
  })

  it('an error shows no values at all and says why, in plain words', () => {
    render(<TelemetryReadout view={{ kind: 'error', code: 'vehicle_link_down', message: 'x' }} services={online} now={T0} />)
    for (const id of ['rpm', 'speed', 'coolant']) expect(screen.getByTestId(`reading-${id}`)).toHaveTextContent('—')
    expect(screen.getByTestId('telemetry-note')).toHaveTextContent('Sem leitura: A ligação OCTAVE ↔ veículo caiu.')
  })

  it("a reading older than the Core's freshness limit is marked out of date", () => {
    render(<TelemetryReadout view={ok()} services={online} now={T0 + 25_000} />)
    expect(screen.getByTestId('telemetry')).toHaveAttribute('data-stale')
    expect(screen.getByTestId('telemetry-note')).toHaveTextContent('Leitura desatualizada (há 25 s)')
  })

  it('makes no judgement and shows nothing the Core does not provide', () => {
    const { container } = render(<TelemetryReadout view={ok(reading({ rpm: 9000, coolant_temp_c: 130 }))} services={online} now={T0} />)
    expect(container.textContent).not.toMatch(/normal|anormal|alta|baixa|perigo|alerta|crític|bateria|pneu|falha|código|diagnóstico|volts?|psi|bar\b/i)
    expect(container.querySelectorAll('button, input, a')).toHaveLength(0)
  })

  it('has an accessible name that carries the origin', () => {
    render(<TelemetryReadout view={ok()} services={online} now={T0} />)
    expect(screen.getByRole('region', { name: /telemetria.*dados simulados/i })).toBeInTheDocument()
  })
})

describe('useTelemetry', () => {
  const apiFor = (telemetry: FitAiApi['telemetry']): FitAiApi => ({ health: vi.fn(), status: vi.fn(), llmStatus: vi.fn(), chat: vi.fn(), telemetry })

  it('asks nothing while disabled', () => {
    const a = apiFor(vi.fn())
    const { result } = renderHook(() => useTelemetry(false, a))
    expect(result.current).toEqual({ kind: 'idle' })
    expect(a.telemetry).not.toHaveBeenCalled()
  })

  it('reads, then keeps reading on the interval, and never calls chat', async () => {
    const t = vi.fn().mockResolvedValue(reading())
    const a = apiFor(t)
    const { result, unmount } = renderHook(() => useTelemetry(true, a, 30))
    await waitFor(() => expect(result.current.kind).toBe('ok'))
    await waitFor(() => expect(t.mock.calls.length).toBeGreaterThanOrEqual(3))
    expect(a.chat).not.toHaveBeenCalled()
    unmount()
  })

  it('never has two requests in flight (a slow source does not pile them up)', async () => {
    let inflight = 0
    let peak = 0
    const slow = vi.fn(async () => {
      inflight++
      peak = Math.max(peak, inflight)
      await new Promise((r) => setTimeout(r, 40))
      inflight--
      return reading()
    })
    const { unmount } = renderHook(() => useTelemetry(true, apiFor(slow), 5))
    await new Promise((r) => setTimeout(r, 300))
    unmount()
    expect(peak).toBe(1)
  })

  it('an API error replaces the readings (the last good values are not kept as if current)', async () => {
    const t = vi.fn().mockResolvedValueOnce(reading()).mockRejectedValue(new ApiError(503, 'octave_unavailable', 'down'))
    const { result } = renderHook(() => useTelemetry(true, apiFor(t), 250)) // long enough for the first state to be observed
    await waitFor(() => expect(result.current.kind).toBe('ok'))
    await waitFor(() => expect(result.current).toMatchObject({ kind: 'error', code: 'octave_unavailable' }), { timeout: 3000 })
  })

  it('maps network failures and odd errors to controlled states', async () => {
    const cases: Array<[Error, string]> = [
      [new NetworkError('offline', 'x'), 'core_offline'],
      [new NetworkError('timeout', 'x'), 'octave_timeout'],
      [new Error('boom'), 'invalid_response'],
    ]
    for (const [err, code] of cases) {
      const { result, unmount } = renderHook(() => useTelemetry(true, apiFor(vi.fn().mockRejectedValue(err)), 1000))
      await waitFor(() => expect(result.current).toMatchObject({ kind: 'error', code }))
      unmount()
    }
  })

  it('stops for good when unmounted (no timer left behind)', async () => {
    vi.useFakeTimers()
    const t = vi.fn().mockResolvedValue(reading())
    const { unmount } = renderHook(() => useTelemetry(true, apiFor(t), TELEMETRY_POLL_MS))
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })
    unmount()
    expect(vi.getTimerCount()).toBe(0)
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000)
    })
    expect(t).toHaveBeenCalledTimes(1)
  })
})
