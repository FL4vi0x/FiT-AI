import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import App from './App'
import { ApiError, NetworkError, type FitAiApi } from './api/client'
import type { ChatResponse, StatusResponse, TelemetryResponse } from './api/types'

const status: StatusResponse = { available: true, state: 'connected', source: 'octave', simulated: true, protocol_version: 3, octave_version: '0.9.6', detail: null }
const reading = (over: Partial<TelemetryResponse> = {}): TelemetryResponse => ({ rpm: 820, speed_kmh: 0, coolant_temp_c: 90, missing: [], source: 'octave', simulated: true, timestamp: new Date().toISOString(), ...over })
const answer = (over: Partial<ChatResponse> = {}): ChatResponse => ({
  conversation_id: 'c0ffee00c0ffee00c0ffee00c0ffee00',
  request_id: 'r1',
  answer: 'No simulador, o motor está a 820 rpm.',
  model: 'qwen3:4b',
  answer_origin: 'llm',
  used_tools: ['get_vehicle_telemetry'],
  fallback_used: false,
  data_source: 'octave',
  simulated: true,
  availability: 'ok',
  model_status: 'ok',
  memory_saved: false,
  history_saved: true,
  replayed: false,
  latency_ms: 4620,
  ...over,
})

function fakeApi(over: Partial<FitAiApi> = {}): FitAiApi {
  return {
    health: vi.fn(async () => ({ status: 'ok', service: 'fit-ai-core', version: '0.1.0' })),
    status: vi.fn(async () => status),
    telemetry: vi.fn(async () => reading()),
    llmStatus: vi.fn(async () => ({ state: 'available' as const, model: 'm:t', checked_at: new Date().toISOString() })),
    voiceStatus: vi.fn(async () => ({ state: 'available' as const, language: 'pt', max_audio_s: 30, sample_rate: 16000, hint: null })),
    transcribe: vi.fn(),
    chat: vi.fn(async () => answer()),
    ...over,
  }
}
// a long poll so the tests control every call; a short "responding" so the core settles quickly
const options = { pollMs: 600_000, respondingMs: 50 }
const renderApp = (api: FitAiApi, opts = options) => render(<App api={api} options={opts} />)
const mode = () => screen.getByTestId('app').getAttribute('data-mode')
const cluster = () => screen.getByTestId('status-cluster')
const online = () => waitFor(() => expect(cluster()).toHaveAttribute('data-octave', 'connected'))

describe('App (real components, fake API)', () => {
  it('boots with real health + status checks and stays clean: one indicator, nothing projected', async () => {
    const api = fakeApi()
    renderApp(api)
    await online()
    expect(cluster()).toHaveAttribute('data-core', 'online')
    expect(cluster()).toHaveAttribute('data-simulated', 'true')
    expect(cluster()).toHaveTextContent('Simulador OCTAVE')
    expect(api.health).toHaveBeenCalled()
    expect(api.status).toHaveBeenCalled()
    expect(api.telemetry).not.toHaveBeenCalled() // telemetry is never read while idle
    expect(mode()).toBe('idle')
    for (const id of ['callout-rpm', 'callout-system', 'provenance']) expect(screen.queryByTestId(id)).toBeNull()
    // the real boot lines are one click away
    await userEvent.click(cluster())
    expect(screen.getByTestId('activity-feed')).toHaveTextContent('Core')
  })

  it('scans on demand: floating readings, and ONE provenance line (simulated, how old) instead of a badge per number', async () => {
    const api = fakeApi()
    renderApp(api)
    await online()
    await userEvent.click(screen.getByTestId('scan-button'))
    await screen.findByTestId('callout-rpm')
    expect(api.telemetry).toHaveBeenCalledTimes(1)
    expect(screen.getByTestId('callout-rpm-value')).toHaveTextContent('820')
    expect(screen.getByTestId('callout-speed-value')).toHaveTextContent('0')
    expect(screen.getByTestId('callout-temp-value')).toHaveTextContent('90')
    expect(screen.getByTestId('provenance-text')).toHaveTextContent(/^Simulado · lido (agora|há \d+ s)$/)
    for (const id of ['callout-rpm', 'callout-speed', 'callout-temp']) expect(screen.getByTestId(id)).not.toHaveTextContent(/simulad|agora|há \d/i) // told once, not once per number
    expect(mode()).toBe('presenting')
  })

  it('chat: sends the question, one quiet line under a plain answer, then projects a direct reading', async () => {
    const api = fakeApi()
    renderApp(api)
    await online()
    await userEvent.type(screen.getByTestId('chat-input'), 'Qual a rotação?{Enter}')
    expect(api.chat).toHaveBeenCalledWith({ message: 'Qual a rotação?', conversation_id: null })
    const bubble = await screen.findByTestId('message-assistant')
    expect(within(bubble).getByTestId('message-summary')).toHaveTextContent('Consultou a telemetria · dados simulados')
    expect(within(bubble).queryByTestId('tool-badge')).toBeNull() // the tool's details are one tap away, not painted on the answer
    await screen.findByTestId('callout-rpm')
    expect(api.telemetry).toHaveBeenCalledTimes(1)
    expect(cluster()).toHaveAttribute('data-ollama', 'online')
    await userEvent.click(within(bubble).getByTestId('message-info'))
    expect(within(bubble).getByTestId('tool-badge')).toHaveTextContent('Telemetria')
    // the next question continues the same conversation
    await userEvent.type(screen.getByTestId('chat-input'), 'e a velocidade?{Enter}')
    await waitFor(() => expect(api.chat).toHaveBeenCalledTimes(2))
    expect(api.chat).toHaveBeenLastCalledWith({ message: 'e a velocidade?', conversation_id: 'c0ffee00c0ffee00c0ffee00c0ffee00' })
  })

  it('"Nova conversa" stops continuing the old one', async () => {
    const api = fakeApi()
    renderApp(api)
    await online()
    await userEvent.type(screen.getByTestId('chat-input'), 'oi{Enter}')
    await screen.findByTestId('message-assistant')
    await userEvent.click(screen.getByTestId('new-conversation'))
    await waitFor(() => expect(screen.queryByTestId('message-assistant')).toBeNull())
    await userEvent.type(screen.getByTestId('chat-input'), 'outra{Enter}')
    await waitFor(() => expect(api.chat).toHaveBeenCalledTimes(2))
    expect(api.chat).toHaveBeenLastCalledWith({ message: 'outra', conversation_id: null })
  })

  it('a chat without tools stays a conversation: no summary line, nothing projected, the car is not read', async () => {
    const api = fakeApi({ chat: vi.fn(async () => answer({ used_tools: [], simulated: null, availability: 'not_requested', data_source: null })) })
    renderApp(api)
    await online()
    await userEvent.type(screen.getByTestId('chat-input'), 'O que é troca de óleo?{Enter}')
    const bubble = await screen.findByTestId('message-assistant')
    expect(within(bubble).queryByTestId('message-summary')).toBeNull()
    expect(api.telemetry).not.toHaveBeenCalled()
    expect(screen.queryByTestId('callout-rpm')).toBeNull()
    await userEvent.click(within(bubble).getByTestId('message-info'))
    expect(within(bubble).getByTestId('message-info-popover')).toHaveTextContent('Só conversa')
  })

  it('a fallback is never silent: the exception is written under the answer', async () => {
    const api = fakeApi({ chat: vi.fn(async () => answer({ answer_origin: 'fallback', fallback_used: true })) })
    renderApp(api)
    await online()
    await userEvent.type(screen.getByTestId('chat-input'), 'Qual a rotação?{Enter}')
    const bubble = await screen.findByTestId('message-assistant')
    expect(within(bubble).getByTestId('note-fallback')).toHaveTextContent('sem o modelo')
  })

  it('a partial reading shows the missing field as unavailable, never as zero', async () => {
    const api = fakeApi({ telemetry: vi.fn(async () => reading({ speed_kmh: null, coolant_temp_c: null, missing: ['speed_kmh', 'coolant_temp_c'] })) })
    renderApp(api)
    await online()
    await userEvent.click(screen.getByTestId('scan-button'))
    await screen.findByTestId('callout-speed')
    expect(screen.getByTestId('callout-rpm-value')).toHaveTextContent('820')
    expect(screen.getByTestId('callout-speed')).toHaveTextContent('indisponível')
    expect(screen.queryByTestId('callout-speed-value')).toBeNull()
    expect(screen.getByTestId('callout-temp')).toHaveTextContent('indisponível')
  })

  it('no reading at all (OCTAVE down): an unavailable state with the real error code', async () => {
    const api = fakeApi({ telemetry: vi.fn(async () => { throw new ApiError(503, 'octave_unavailable', 'OCTAVE unavailable') }) })
    renderApp(api)
    await online()
    await userEvent.click(screen.getByTestId('scan-button'))
    await screen.findByTestId('system-error')
    expect(screen.getByTestId('system-error')).toHaveTextContent('octave_unavailable')
    expect(mode()).toBe('unavailable')
    expect(screen.queryByTestId('callout-rpm')).toBeNull()
  })

  it('a slow telemetry read is "no reading", not "Core offline"', async () => {
    const api = fakeApi({ telemetry: vi.fn(async () => { throw new NetworkError('timeout', 'slow') }) })
    renderApp(api)
    await online()
    await userEvent.click(screen.getByTestId('scan-button'))
    await screen.findByTestId('system-error')
    expect(screen.getByTestId('system-error')).toHaveTextContent('timeout')
    expect(mode()).toBe('unavailable')
    expect(cluster()).toHaveAttribute('data-core', 'online')
  })

  it('chat errors are shown with the retry hint and teach the model status', async () => {
    const chat = vi.fn()
    chat.mockRejectedValueOnce(new ApiError(429, 'service_busy', 'busy', 'req123', 10))
    chat.mockRejectedValueOnce(new ApiError(503, 'model_unavailable', 'down', 'req456'))
    renderApp(fakeApi({ chat }))
    await online()
    await userEvent.type(screen.getByTestId('chat-input'), 'oi{Enter}')
    const first = await screen.findByTestId('message-error')
    expect(first).toHaveTextContent('service_busy')
    expect(first).toHaveTextContent('10 s')
    await userEvent.type(screen.getByTestId('chat-input'), 'oi de novo{Enter}')
    await waitFor(() => expect(screen.getAllByTestId('message-error')).toHaveLength(2))
    expect(cluster()).toHaveAttribute('data-ollama', 'offline')
    expect(cluster()).toHaveTextContent('Modelo indisponível')
  })

  it('offline: the Core is unreachable, the UI says so calmly and blocks the input', async () => {
    const api = fakeApi({ health: vi.fn(async () => { throw new NetworkError('offline', 'down') }) })
    renderApp(api)
    await screen.findByTestId('offline-banner')
    expect(mode()).toBe('offline')
    expect(cluster()).toHaveAttribute('data-core', 'offline')
    expect(cluster()).toHaveTextContent('Core offline')
    expect(screen.getByTestId('chat-input')).toBeDisabled()
    expect(screen.getByTestId('scan-button')).toBeDisabled()
    expect(api.status).not.toHaveBeenCalled() // no point asking OCTAVE through a dead Core
  })

  it('clear removes the projection, live mode refreshes the reading and stops when cleared', async () => {
    const api = fakeApi()
    render(<App api={api} options={{ ...options, liveMs: 40 }} />)
    await online()
    await userEvent.click(screen.getByTestId('scan-button'))
    await screen.findByTestId('callout-rpm')
    await userEvent.click(screen.getByTestId('live-button'))
    await waitFor(() => expect((api.telemetry as ReturnType<typeof vi.fn>).mock.calls.length).toBeGreaterThanOrEqual(3))
    await userEvent.click(screen.getByTestId('clear-button'))
    await waitFor(() => expect(mode()).toBe('idle'))
    const frozen = (api.telemetry as ReturnType<typeof vi.fn>).mock.calls.length
    await new Promise((r) => setTimeout(r, 200))
    expect((api.telemetry as ReturnType<typeof vi.fn>).mock.calls.length).toBe(frozen)
  })
})
