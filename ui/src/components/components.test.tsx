import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import type { ChatResponse } from '../api/types'
import { ZONES } from '../lib/vehicleZones'
import type { ChatEntry, CoreLink, FeedEvent, OctaveLink, OllamaLink } from '../state/store'
import { ActivityFeed } from './ActivityFeed'
import { AnimatedGridBackground } from './AnimatedGridBackground'
import { ChatPanel } from './ChatPanel'
import { ConnectionLine } from './ConnectionLine'
import { FitAICore } from './FitAICore'
import { HoloPanel } from './HoloPanel'
import { MessageBubble, isVerified, quietSummary } from './MessageBubble'
import { StatusBadge } from './StatusBadge'
import { TelemetryCallout } from './TelemetryCallout'
import { TelemetryGauge } from './TelemetryGauge'
import { ToolBadge } from './ToolBadge'
import { TopSystemBar, summarize } from './TopSystemBar'
import { VehicleHero } from './VehicleHero'
import { VehicleHighlightZone } from './VehicleHighlightZone'

const meta = (over: Partial<ChatResponse> = {}): ChatResponse => ({
  conversation_id: 'c0ffee00c0ffee00c0ffee00c0ffee00',
  request_id: 'r1',
  answer: 'No simulador, o motor está a 820 rpm.',
  model: 'qwen3:4b-instruct-2507-q4_K_M',
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
const assistant = (m: Partial<ChatResponse> = {}): ChatEntry => ({ id: 'a', role: 'assistant', text: 'resposta', at: 0, meta: meta(m) })

describe('StatusBadge / ToolBadge: quiet notes, not pills', () => {
  it('shows its label and tone, with an optional dot, and has no box', () => {
    render(<StatusBadge label="Resposta montada pelo sistema" tone="warn" dot title="dica" />)
    const b = screen.getByText('Resposta montada pelo sistema')
    expect(b).toHaveAttribute('data-tone', 'warn')
    expect(b).toHaveAttribute('title', 'dica')
    expect(b.className).not.toMatch(/border|uppercase|tracking/)
  })

  it('names a tool in Portuguese and says in words that it only reads', () => {
    render(<ToolBadge name="get_vehicle_telemetry" />)
    const b = screen.getByTestId('tool-badge')
    expect(b).toHaveTextContent('Telemetria')
    expect(b).toHaveTextContent('somente leitura')
    expect(b).toHaveAttribute('data-tool', 'get_vehicle_telemetry')
  })
})

describe('TelemetryGauge', () => {
  it('exposes the value as an accessible meter', () => {
    render(<TelemetryGauge label="Rotação" unit="rpm" value={820} min={0} max={8000} />)
    const g = screen.getByRole('meter')
    expect(g).toHaveAttribute('aria-valuenow', '820')
    expect(g).toHaveAttribute('aria-label', 'Rotação: 820 rpm')
    expect(g).toHaveAttribute('data-available', 'true')
  })

  it('a missing reading is an empty track, never a zero', () => {
    render(<TelemetryGauge label="Velocidade" unit="km/h" value={null} min={0} max={200} />)
    expect(screen.queryByRole('meter')).toBeNull()
    expect(screen.getByRole('img', { name: /indisponível/i })).toHaveAttribute('data-available', 'false')
  })

  it('does not colour or flag a value as normal/high: there are no approved thresholds', () => {
    const { container } = render(<TelemetryGauge label="Temperatura" unit="°C" value={125} min={40} max={130} />)
    expect(container.innerHTML).not.toMatch(/bg-(err|warn)|var\(--(err|warn)\)/)
  })
})

describe('TelemetryCallout: a floating reading, no box and no badges', () => {
  const base = { testId: 'callout-rpm', label: 'Rotação', unit: 'rpm', min: 0, max: 8000, stale: false }

  it('shows the label, a large numeral, the unit and a hairline scale; it says nothing about simulation (the provenance line does)', () => {
    render(<TelemetryCallout {...base} value={820} />)
    const c = screen.getByTestId('callout-rpm')
    expect(screen.getByTestId('callout-rpm-value')).toHaveTextContent('820')
    expect(c).toHaveTextContent('Rotação')
    expect(c).toHaveTextContent('rpm')
    expect(c).not.toHaveTextContent(/simulado|leitura direta|agora|há \d/i)
    expect(within(c).getByRole('meter')).toBeInTheDocument()
    expect(c.className).not.toMatch(/border|shadow/)
  })

  it('dims the numeral of a stale reading instead of presenting it as current', () => {
    render(<TelemetryCallout {...base} value={820} stale />)
    expect(screen.getByTestId('callout-rpm')).toHaveAttribute('data-stale', 'true')
    expect(screen.getByTestId('callout-rpm-value').className).toMatch(/text-ink-dim/)
  })

  it('a field the source did not provide says "indisponível" and has no numeric value', () => {
    render(<TelemetryCallout {...base} value={null} />)
    const c = screen.getByTestId('callout-rpm')
    expect(c).toHaveAttribute('data-missing', 'true')
    expect(c).toHaveTextContent('indisponível')
    expect(c).toHaveTextContent('—')
    expect(screen.queryByTestId('callout-rpm-value')).toBeNull()
  })
})

describe('FitAICore: a quiet light, no label', () => {
  it.each([
    ['idle', 'em espera'],
    ['scanning', 'consultando o veículo'],
    ['thinking', 'pensando'],
    ['responding', 'respondendo'],
    ['offline', 'offline'],
  ] as const)('renders the %s state', (state, label) => {
    render(<FitAICore state={state} />)
    const c = screen.getByTestId('fit-ai-core')
    expect(c).toHaveAttribute('data-state', state)
    expect(c).toHaveAttribute('aria-label', `Fit AI: ${label}`)
    expect(c.textContent).toBe('') // nothing is written on screen: the state is read from the motion
  })
})

describe('MessageBubble: provenance on demand', () => {
  it('shows one quiet line (what it looked at, simulated) and no pills', () => {
    render(<ul><MessageBubble entry={assistant()} /></ul>)
    expect(screen.getByTestId('message-summary')).toHaveTextContent('Consultou a telemetria · dados simulados')
    const meta = screen.getByTestId('message-meta')
    expect(meta).not.toHaveTextContent(/verificada|modelo|completo|read/i)
    expect(screen.queryByTestId('message-info-popover')).toBeNull()
    expect(screen.queryByTestId('note-fallback')).toBeNull()
  })

  it('opens the details only on request: who wrote it, the tool (read-only), the verification, the data', async () => {
    render(<ul><MessageBubble entry={assistant()} /></ul>)
    await userEvent.click(screen.getByTestId('message-info'))
    const p = screen.getByTestId('message-info-popover')
    expect(p).toHaveTextContent('Escrita pelo modelo')
    expect(p).toHaveTextContent('qwen3')
    expect(within(p).getByTestId('tool-badge')).toHaveTextContent('Telemetria')
    expect(p).toHaveTextContent('conferidos pelo sistema')
    expect(p).toHaveTextContent('dado completo')
    expect(screen.getByTestId('message-info')).toHaveAttribute('aria-expanded', 'true')
    await userEvent.click(screen.getByTestId('message-info'))
    expect(screen.queryByTestId('message-info-popover')).toBeNull()
  })

  it('always shows the exceptions: fallback, partial and unavailable readings, a model problem', () => {
    const { unmount } = render(<ul><MessageBubble entry={assistant({ answer_origin: 'fallback', fallback_used: true, availability: 'partial' })} /></ul>)
    expect(screen.getByTestId('note-fallback')).toHaveTextContent('montada pelo sistema')
    expect(screen.getByTestId('note-availability')).toHaveTextContent('parcial')
    unmount()
    render(<ul><MessageBubble entry={assistant({ availability: 'unavailable', model_status: 'timeout' })} /></ul>)
    expect(screen.getByTestId('note-availability')).toHaveTextContent('Sem leitura')
    expect(screen.getByTestId('note-model')).toHaveTextContent('excedeu')
  })

  it('a conversation without tools has no summary line, and the details say so', async () => {
    render(<ul><MessageBubble entry={assistant({ used_tools: [], simulated: null, availability: 'not_requested', data_source: null })} /></ul>)
    expect(screen.queryByTestId('message-summary')).toBeNull()
    await userEvent.click(screen.getByTestId('message-info'))
    expect(screen.getByTestId('message-info-popover')).toHaveTextContent('Só conversa')
    expect(screen.getByTestId('message-info-popover')).not.toHaveTextContent('conferidos')
  })

  it('says "dados reais" when the source is real', () => {
    expect(quietSummary(meta({ simulated: false }))).toBe('Consultou a telemetria · dados reais')
    expect(quietSummary(meta({ used_tools: ['get_vehicle_status'], simulated: true }))).toBe('Consultou o status do veículo · dados simulados')
    expect(quietSummary(meta({ used_tools: [] }))).toBeNull()
  })

  it('isVerified is only true for answers that used telemetry and came from the model or from code', () => {
    expect(isVerified(meta())).toBe(true)
    expect(isVerified(meta({ answer_origin: 'llm_retry' }))).toBe(true)
    expect(isVerified(meta({ answer_origin: 'policy_refusal' }))).toBe(false)
    expect(isVerified(meta({ answer_origin: 'memory_command' }))).toBe(false)
    expect(isVerified(meta({ used_tools: ['get_memory_facts'] }))).toBe(false)
  })

  it('renders user text as text (no HTML injection) and errors with their code and request id', () => {
    const user: ChatEntry = { id: 'u', role: 'user', text: '<img src=x onerror=alert(1)>', at: 0 }
    const err: ChatEntry = { id: 'e', role: 'error', text: 'O assistente está ocupado.', at: 0, code: 'service_busy', requestId: 'abcdef0123456789' }
    const { container } = render(<ul><MessageBubble entry={user} /><MessageBubble entry={err} /></ul>)
    expect(container.querySelector('img')).toBeNull()
    expect(screen.getByTestId('message-user')).toHaveTextContent('<img src=x onerror=alert(1)>')
    expect(screen.getByTestId('message-error')).toHaveTextContent('service_busy')
    expect(screen.getByTestId('message-error')).toHaveTextContent('abcdef012345')
  })
})

describe('TopSystemBar: one quiet indicator', () => {
  const core = (over: Partial<CoreLink> = {}): CoreLink => ({ status: 'online', version: '0.1.0', latencyMs: 12, ...over })
  const octave = (over: Partial<OctaveLink> = {}): OctaveLink => ({ status: 'connected', state: 'connected', simulated: true, source: 'octave', octaveVersion: '0.9.6', protocolVersion: 3, detail: null, ...over })
  const ollama = (over: Partial<OllamaLink> = {}): OllamaLink => ({ status: 'unknown', detail: null, ...over })
  const feed: FeedEvent[] = [{ id: 1, at: 0, tag: 'CORE', text: 'Fit AI Core v0.1.0 online', level: 'ok' }]
  const bar = (c: CoreLink, o: OctaveLink, l: OllamaLink) => render(<TopSystemBar core={c} octave={o} ollama={l} nowMs={new Date(2026, 10, 21, 9, 5, 3).getTime()} feed={feed} />)

  it('shows the clock and ONE sentence for the whole link; nothing else on the bar', () => {
    bar(core(), octave(), ollama())
    expect(screen.getByTestId('clock')).toHaveTextContent('09:05:03')
    const c = screen.getByTestId('status-cluster')
    expect(c).toHaveTextContent('Simulador OCTAVE')
    expect(c).toHaveAttribute('data-level', 'ok')
    expect(c).toHaveAttribute('data-core', 'online')
    expect(c).toHaveAttribute('data-octave', 'connected')
    expect(c).toHaveAttribute('data-ollama', 'unknown')
    expect(c).toHaveAttribute('data-simulated', 'true')
    expect(screen.queryByTestId('status-popover')).toBeNull()
  })

  it('opens the details on request (Core, OCTAVE, model, activity) and closes with Escape', async () => {
    bar(core(), octave(), ollama())
    await userEvent.click(screen.getByTestId('status-cluster'))
    expect(screen.getByTestId('status-core')).toHaveTextContent('online · v0.1.0')
    expect(screen.getByTestId('status-octave')).toHaveTextContent('dados simulados')
    expect(screen.getByTestId('status-octave')).toHaveTextContent('protocolo v3')
    expect(screen.getByTestId('status-ollama')).toHaveTextContent('deduzido do chat')
    expect(screen.getByTestId('activity-feed')).toHaveTextContent('Fit AI Core v0.1.0 online')
    await userEvent.keyboard('{Escape}')
    expect(screen.queryByTestId('status-popover')).toBeNull()
  })

  it('the worst thing that is true wins: error over warning over all-good', () => {
    expect(summarize(core({ status: 'offline' }), octave(), ollama()).level).toBe('error')
    expect(summarize(core(), octave({ status: 'unreachable' }), ollama()).label).toBe('OCTAVE fora do ar')
    expect(summarize(core(), octave({ status: 'degraded' }), ollama()).label).toBe('OCTAVE sem veículo')
    expect(summarize(core(), octave(), ollama({ status: 'offline' })).label).toBe('Modelo indisponível')
    expect(summarize(core(), octave(), ollama({ status: 'degraded' })).level).toBe('warn')
    expect(summarize(core(), octave({ simulated: false }), ollama()).label).toBe('OCTAVE conectado')
    expect(summarize(core({ status: 'checking' }), octave({ status: 'unknown' }), ollama()).level).toBe('idle')
  })
})

describe('ChatPanel', () => {
  const user: ChatEntry = { id: 'u', role: 'user', text: 'oi', at: 0 }
  const setup = (over: Partial<React.ComponentProps<typeof ChatPanel>> = {}) => {
    const onSend = vi.fn(async () => true)
    const onNew = vi.fn()
    render(<ChatPanel entries={[]} busy={false} offline={false} onSend={onSend} onNewConversation={onNew} {...over} />)
    return { onSend, onNew }
  }

  it('sends on Enter, clears the box at once, and does not send on Shift+Enter', async () => {
    const { onSend } = setup()
    const input = screen.getByTestId('chat-input')
    await userEvent.type(input, 'Qual a rotação?{Shift>}{Enter}{/Shift}')
    expect(onSend).not.toHaveBeenCalled()
    await userEvent.clear(input)
    await userEvent.type(input, 'Qual a rotação?{Enter}')
    expect(onSend).toHaveBeenCalledWith('Qual a rotação?')
    expect(input).toHaveValue('')
  })

  it('gives the text back when the message was not accepted', async () => {
    setup({ onSend: vi.fn(async () => false) })
    const input = screen.getByTestId('chat-input')
    await userEvent.type(input, 'oi{Enter}')
    expect(input).toHaveValue('oi')
  })

  it('offers three suggestions on an empty conversation and sends one with a tap', async () => {
    const { onSend } = setup()
    expect(within(screen.getByTestId('suggestions')).getAllByRole('button')).toHaveLength(3)
    await userEvent.click(screen.getByText('Qual a minha velocidade?'))
    expect(onSend).toHaveBeenCalledWith('Qual a minha velocidade?')
  })

  it('hides the suggestions and offers "Nova conversa" once the conversation has started', async () => {
    const { onNew } = setup({ entries: [user] })
    expect(screen.queryByTestId('suggestions')).toBeNull()
    await userEvent.click(screen.getByTestId('new-conversation'))
    expect(onNew).toHaveBeenCalled()
  })

  it('is disabled and explains why while the Core is offline', () => {
    setup({ offline: true })
    expect(screen.getByTestId('chat-input')).toBeDisabled()
    expect(screen.getByTestId('chat-input')).toHaveAttribute('placeholder', expect.stringContaining('offline'))
    expect(screen.getByTestId('chat-send')).toBeDisabled()
    for (const chip of within(screen.getByTestId('suggestions')).getAllByRole('button')) expect(chip).toBeDisabled()
  })

  it('shows the thinking indicator while busy and blocks a second send and a reset', () => {
    setup({ busy: true, entries: [user] })
    expect(screen.getByTestId('thinking-indicator')).toBeInTheDocument()
    expect(screen.getByTestId('chat-input')).toBeDisabled()
    expect(screen.getByTestId('new-conversation')).toBeDisabled()
  })

  it('caps the message at the Core limit', () => {
    setup()
    expect(screen.getByTestId('chat-input')).toHaveAttribute('maxlength', '1000')
  })
})

describe('ActivityFeed', () => {
  it('shows only the latest events, oldest first, in plain lower-case tags', () => {
    const events = Array.from({ length: 9 }, (_, i) => ({ id: i + 1, at: 0, tag: 'CORE', text: `evento ${i + 1}`, level: 'info' as const }))
    render(<ActivityFeed events={events} max={4} />)
    expect(screen.getByRole('log')).toBeInTheDocument()
    expect(screen.queryByText('evento 5')).toBeNull()
    expect(screen.getByText('evento 6')).toBeInTheDocument()
    expect(screen.getByText('evento 9')).toBeInTheDocument()
    expect(screen.getAllByText('core')).toHaveLength(4)
  })
})

describe('HoloPanel / ConnectionLine / zones / hero / background', () => {
  it('HoloPanel is one plain surface with its title, badge and content', () => {
    render(<HoloPanel title="Estado" badge={<span>nota</span>} data-testid="p">conteúdo</HoloPanel>)
    const p = screen.getByTestId('p')
    expect(p).toHaveTextContent('Estado')
    expect(p).toHaveTextContent('nota')
    expect(p).toHaveTextContent('conteúdo')
    expect(p.className).not.toMatch(/backdrop-blur|shadow-holo/)
  })

  it('ConnectionLine draws a hairline along its points inside an svg, dashed when it points at nothing', () => {
    const { container } = render(
      <svg>
        <ConnectionLine testId="l" points={[{ x: 0, y: 0 }, { x: 0, y: 10 }, { x: 20, y: 10 }]} dashed />
      </svg>,
    )
    expect(screen.getByTestId('l')).toBeInTheDocument()
    expect(container.querySelector('path')?.getAttribute('d')).toBe('M 0.0 0.0 L 0.0 10.0 L 20.0 10.0')
    expect(container.querySelector('path')?.getAttribute('stroke-dasharray')).toBe('4 5')
  })

  it('VehicleHighlightZone reflects active and faulty state and paints no label on the car', () => {
    const { rerender, container } = render(<svg><VehicleHighlightZone zone={ZONES.powertrain} active /></svg>)
    expect(screen.getByTestId('zone-powertrain')).toHaveAttribute('data-active', 'true')
    expect(container.querySelector('text')).toBeNull()
    rerender(<svg><VehicleHighlightZone zone={ZONES.cabin} active={false} faulty /></svg>)
    expect(screen.getByTestId('zone-cabin')).toHaveAttribute('data-faulty', 'true')
    expect(screen.getByTestId('zone-cabin')).toHaveAttribute('data-active', 'true')
  })

  it('VehicleHero is labelled, lights the requested zones and only draws the scan while scanning', () => {
    const { rerender } = render(<VehicleHero activeZones={['powertrain']} faultyZones={[]} scanning={false} offline={false} />)
    expect(screen.getByRole('img', { name: /Honda Fit 2005/ })).toBeInTheDocument()
    expect(screen.getByTestId('zone-powertrain')).toHaveAttribute('data-active', 'true')
    expect(screen.getByTestId('zone-motion')).toHaveAttribute('data-active', 'false')
    expect(screen.queryByTestId('scan-layer')).toBeNull()
    rerender(<VehicleHero activeZones={[]} faultyZones={[]} scanning offline={false} />)
    expect(screen.getByTestId('scan-layer')).toBeInTheDocument()
    rerender(<VehicleHero activeZones={[]} faultyZones={[]} scanning={false} offline />)
    expect(screen.getByTestId('vehicle-hero')).toHaveAttribute('data-offline', 'true')
  })

  it('AnimatedGridBackground is decorative: aria-hidden and static', () => {
    const { container } = render(<AnimatedGridBackground />)
    expect(screen.getByTestId('grid-background')).toHaveAttribute('aria-hidden', 'true')
    expect(container.innerHTML).not.toMatch(/animation|hud-grid|scanline/)
  })
})
