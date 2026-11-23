import { motion } from 'motion/react'
import { useState } from 'react'
import { TOOL_MEMORY, TOOL_STATUS, TOOL_TELEMETRY, type ChatResponse } from '../api/types'
import { fmtClock, fmtLatency } from '../lib/format'
import { AVAILABILITY_META, MODEL_STATUS_TEXT, ORIGIN_META } from '../lib/labels'
import type { ChatEntry } from '../state/store'
import { StatusBadge } from './StatusBadge'
import { ToolBadge } from './ToolBadge'

/**
 * "Verified" means what the Core guarantees: when the turn used the telemetry tool, every vehicle number in the answer was
 * checked by code against the reading of that same turn (or the answer was built by code from it).
 */
export function isVerified(meta: ChatResponse): boolean {
  return meta.used_tools.includes(TOOL_TELEMETRY) && ['llm', 'llm_retry', 'fallback', 'deterministic'].includes(meta.answer_origin)
}

const CONSULTED: Record<string, string> = {
  [TOOL_TELEMETRY]: 'a telemetria',
  [TOOL_STATUS]: 'o status do veículo',
  [TOOL_MEMORY]: 'suas notas',
}

/** The one quiet line under an answer: what it looked at and whether that data is simulated. Nothing when it only talked. */
export function quietSummary(meta: ChatResponse): string | null {
  if (meta.used_tools.length === 0) return null
  const names = meta.used_tools.map((t) => CONSULTED[t] ?? t)
  let line = `Consultou ${names.join(' e ')}`
  if (meta.simulated === true) line += ' · dados simulados'
  else if (meta.simulated === false) line += ' · dados reais'
  return line
}

function originSentence(meta: ChatResponse): string {
  const model = meta.model ? meta.model.split(':')[0] : 'modelo'
  const t = fmtLatency(meta.latency_ms)
  switch (meta.answer_origin) {
    case 'llm':
      return `Escrita pelo modelo (${model} · ${t})`
    case 'llm_retry':
      return `Escrita pelo modelo na 2ª tentativa, depois de a 1ª ser rejeitada (${model} · ${t})`
    case 'fallback':
      return `Montada pelo sistema: o modelo não produziu uma resposta aceita (${t})`
    case 'deterministic':
      return `Montada pelo sistema, sem o modelo (${t})`
    default:
      return `${ORIGIN_META[meta.answer_origin].hint} (${t})`
  }
}

function AnswerInfo({ meta }: { meta: ChatResponse }) {
  const avail = AVAILABILITY_META[meta.availability]
  const dataBits = [avail.label, meta.simulated === true ? 'simulados' : meta.simulated === false ? 'reais' : null, meta.data_source ? `fonte ${meta.data_source}` : null].filter(Boolean)
  return (
    <div data-testid="message-info-popover" role="dialog" aria-label="Como esta resposta foi produzida" className="mt-2 space-y-1.5 rounded-[12px] border border-white/[0.07] bg-base-lift px-3.5 py-3 text-[13px] leading-snug text-ink-soft">
      <p className="m-0">{originSentence(meta)}</p>
      {meta.used_tools.length > 0 ? (
        <div className="flex flex-col gap-1">
          {meta.used_tools.map((t) => (
            <ToolBadge key={t} name={t} />
          ))}
        </div>
      ) : (
        <p className="m-0 text-ink-dim">Só conversa: não consultou o veículo.</p>
      )}
      {isVerified(meta) && <p className="m-0">Os valores do veículo foram conferidos pelo sistema contra a leitura deste turno.</p>}
      {meta.availability !== 'not_requested' && <p className="m-0 text-ink-dim">Dados: {dataBits.join(' · ')}</p>}
    </div>
  )
}

function AssistantFooter({ meta }: { meta: ChatResponse }) {
  const [open, setOpen] = useState(false)
  const summary = quietSummary(meta)
  const avail = AVAILABILITY_META[meta.availability]
  const exceptions: { id: string; text: string; tone: 'warn' | 'error' | 'dim' }[] = []
  if (meta.fallback_used) exceptions.push({ id: 'note-fallback', text: 'Resposta montada pelo sistema, sem o modelo', tone: 'warn' })
  if (meta.availability === 'partial') exceptions.push({ id: 'note-availability', text: 'Leitura parcial: faltou algum valor', tone: 'warn' })
  if (meta.availability === 'stale') exceptions.push({ id: 'note-availability', text: 'Leitura desatualizada', tone: 'warn' })
  if (meta.availability === 'unavailable') exceptions.push({ id: 'note-availability', text: 'Sem leitura disponível', tone: 'dim' })
  if (meta.model_status !== 'ok' && meta.model_status !== 'not_used') exceptions.push({ id: 'note-model', text: MODEL_STATUS_TEXT[meta.model_status], tone: 'warn' })
  return (
    <div className="mt-1.5">
      <div data-testid="message-meta" className="flex flex-wrap items-center gap-x-4 gap-y-0.5 text-[12px] text-ink-dim">
        {summary && <span data-testid="message-summary">{summary}</span>}
        {exceptions.map((x) => (
          <StatusBadge key={x.id} data-testid={x.id} label={x.text} tone={x.tone} dot title={avail.label} />
        ))}
        <button
          type="button"
          data-testid="message-info"
          aria-label="Como esta resposta foi produzida"
          aria-expanded={open}
          onClick={() => setOpen((v) => !v)}
          className="-my-2 grid h-11 w-11 place-items-center rounded-full text-ink-dim transition hover:bg-white/[0.05] hover:text-ink-soft"
        >
          <span aria-hidden className="grid h-[18px] w-[18px] place-items-center rounded-full border border-current text-[11px] font-semibold italic leading-none">
            i
          </span>
        </button>
      </div>
      {open && <AnswerInfo meta={meta} />}
    </div>
  )
}

export interface MessageBubbleProps {
  entry: ChatEntry
}

export function MessageBubble({ entry }: MessageBubbleProps) {
  const enter = { initial: { opacity: 0, y: 8 }, animate: { opacity: 1, y: 0 }, transition: { duration: 0.2 } } as const
  if (entry.role === 'user') {
    return (
      <motion.li {...enter} data-testid="message-user" className="ml-12 self-end" title={fmtClock(entry.at)}>
        <div className="rounded-[18px] rounded-br-[6px] bg-base-lift px-4 py-2.5 text-[16px] leading-snug text-ink">
          <p className="m-0 whitespace-pre-wrap break-words">{entry.text}</p>
        </div>
      </motion.li>
    )
  }
  if (entry.role === 'error') {
    return (
      <motion.li {...enter} data-testid="message-error" className="mr-6">
        <div className="rounded-[12px] bg-err/[0.1] px-3.5 py-2.5 text-[14px] leading-snug text-ink-soft">
          <p className="m-0 break-words">{entry.text}</p>
          <p className="m-0 mt-1 font-mono text-[11px] text-ink-dim">
            {entry.code}
            {entry.requestId ? ` · pedido ${entry.requestId.slice(0, 12)}` : ''}
          </p>
        </div>
      </motion.li>
    )
  }
  return (
    <motion.li {...enter} data-testid="message-assistant" className="mr-6" title={fmtClock(entry.at)}>
      <p className="m-0 whitespace-pre-wrap break-words text-[16px] leading-relaxed text-ink">{entry.text}</p>
      <AssistantFooter meta={entry.meta} />
    </motion.li>
  )
}
