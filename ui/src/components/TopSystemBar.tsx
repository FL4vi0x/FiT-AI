import { useEffect, useRef, useState } from 'react'
import { fmtClock, fmtLatency } from '../lib/format'
import type { CoreLink, FeedEvent, OctaveLink, OllamaLink } from '../state/store'
import { ActivityFeed } from './ActivityFeed'
import { HoloPanel } from './HoloPanel'

export type Level = 'ok' | 'warn' | 'error' | 'idle'

/** One sentence for the whole link: the worst thing that is true wins, and "all good" is just the simulator's name. */
export function summarize(core: CoreLink, octave: OctaveLink, ollama: OllamaLink): { level: Level; label: string } {
  if (core.status === 'offline') return { level: 'error', label: 'Core offline' }
  if (core.status === 'checking') return { level: 'idle', label: 'Conectando…' }
  if (octave.status === 'unreachable') return { level: 'error', label: 'OCTAVE fora do ar' }
  if (octave.status === 'degraded') return { level: 'warn', label: 'OCTAVE sem veículo' }
  if (ollama.status === 'offline') return { level: 'warn', label: 'Modelo indisponível' }
  if (ollama.status === 'degraded') return { level: 'warn', label: 'Modelo instável' }
  if (octave.status === 'connected') return { level: 'ok', label: octave.simulated === true ? 'Simulador OCTAVE' : octave.simulated === false ? 'OCTAVE conectado' : 'OCTAVE conectado · origem não informada' }
  return { level: 'idle', label: 'OCTAVE ainda não consultado' }
}

const DOT: Record<Level, string> = { ok: 'bg-ok', warn: 'bg-warn', error: 'bg-err', idle: 'bg-ink-dim' }

function coreText(c: CoreLink): string {
  if (c.status === 'online') return `online · v${c.version ?? '?'}${c.latencyMs !== null ? ` · ${fmtLatency(c.latencyMs)}` : ''}`
  return c.status === 'checking' ? 'verificando…' : 'sem resposta'
}

function octaveText(o: OctaveLink): string {
  switch (o.status) {
    case 'connected':
      return `conectado · ${o.simulated === true ? 'dados simulados' : o.simulated === false ? 'dados reais' : 'origem não informada'}${o.protocolVersion !== null ? ` · protocolo v${o.protocolVersion}` : ''}${o.octaveVersion ? ` · OCTAVE ${o.octaveVersion}` : ''}`
    case 'degraded':
      return 'responde, mas a ligação com o veículo caiu'
    case 'unreachable':
      return `fora do ar${o.state ? ` (${o.state})` : ''}`
    default:
      return 'ainda não consultado'
  }
}

function ollamaText(o: OllamaLink): string {
  switch (o.status) {
    case 'online':
      return 'respondeu à última pergunta'
    case 'degraded':
      return o.detail ?? 'instável'
    case 'offline':
      return o.detail ?? 'indisponível'
    default:
      return 'ainda não testado (deduzido do chat: o Core não expõe a saúde do Ollama)'
  }
}

function Row({ k, v, testId }: { k: string; v: string; testId: string }) {
  return (
    <div className="flex gap-4 py-1 text-[13px]" data-testid={testId}>
      <dt className="w-[6.5rem] shrink-0 text-ink-dim">{k}</dt>
      <dd className="m-0 min-w-0 text-ink-soft">{v}</dd>
    </div>
  )
}

export interface TopSystemBarProps {
  core: CoreLink
  octave: OctaveLink
  ollama: OllamaLink
  nowMs: number
  feed: FeedEvent[]
}

export function TopSystemBar({ core, octave, ollama, nowMs, feed }: TopSystemBarProps) {
  const [open, setOpen] = useState(false)
  const wrap = useRef<HTMLDivElement>(null)
  const sum = summarize(core, octave, ollama)

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false)
    const onDown = (e: MouseEvent) => wrap.current && !wrap.current.contains(e.target as Node) && setOpen(false)
    document.addEventListener('keydown', onKey)
    document.addEventListener('mousedown', onDown)
    return () => {
      document.removeEventListener('keydown', onKey)
      document.removeEventListener('mousedown', onDown)
    }
  }, [open])

  return (
    <header data-testid="top-bar" className="relative z-20 flex items-center justify-between gap-6 px-6 py-3">
      <div className="font-display text-[13px] font-semibold tracking-[0.18em] text-ink">
        FIT<span className="text-fit-orange"> AI</span>
      </div>

      <div className="flex items-center gap-5">
        <span data-testid="clock" className="text-[15px] tabular-nums text-ink-dim">
          {fmtClock(nowMs)}
        </span>
        <div ref={wrap} className="relative">
          <button
            type="button"
            data-testid="status-cluster"
            data-level={sum.level}
            data-core={core.status}
            data-octave={octave.status}
            data-ollama={ollama.status}
            data-simulated={String(octave.simulated)}
            aria-haspopup="dialog"
            aria-expanded={open}
            onClick={() => setOpen((v) => !v)}
            className="flex min-h-[44px] items-center gap-2.5 rounded-full px-3 text-[14px] text-ink-soft transition hover:bg-white/[0.05]"
          >
            <span aria-hidden className={`h-2 w-2 rounded-full ${DOT[sum.level]}`} style={core.status === 'checking' ? { animation: 'blink 1.1s ease-in-out infinite' } : undefined} />
            <span data-testid="status-label">{sum.label}</span>
          </button>
          {open && (
            <div className="absolute right-0 top-full z-30 mt-2 w-[min(34rem,90vw)]" role="dialog" aria-label="Estado do sistema">
              <HoloPanel data-testid="status-popover" tone="neutral" title="Estado do sistema">
                <dl className="m-0">
                  <Row k="Core" v={coreText(core)} testId="status-core" />
                  <Row k="OCTAVE" v={octaveText(octave)} testId="status-octave" />
                  <Row k="Modelo (Ollama)" v={ollamaText(ollama)} testId="status-ollama" />
                </dl>
                <div className="mt-3 border-t border-white/[0.06] pt-3">
                  <div className="mb-1.5 text-[12px] font-semibold text-ink-dim">Atividade</div>
                  <ActivityFeed events={feed} max={8} />
                </div>
              </HoloPanel>
            </div>
          )}
        </div>
      </div>
    </header>
  )
}
