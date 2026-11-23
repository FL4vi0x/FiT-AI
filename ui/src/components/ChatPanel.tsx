import { useEffect, useLayoutEffect, useRef, useState, type FormEvent, type KeyboardEvent } from 'react'
import { MAX_MESSAGE_CHARS } from '../api/types'
import type { ChatEntry } from '../state/store'
import { MessageBubble } from './MessageBubble'
import { StatusBadge } from './StatusBadge'

const SUGGESTIONS = ['Qual a rotação do motor?', 'Qual a minha velocidade?', 'Qual a temperatura do motor?']

export interface ChatPanelProps {
  entries: ChatEntry[]
  busy: boolean
  /** The Core is unreachable: sending is disabled and the placeholder says why. */
  offline: boolean
  /** Resolves to true when the message was accepted (then the input is cleared). */
  onSend: (text: string) => Promise<boolean>
  onNewConversation: () => void
}

export function ChatPanel({ entries, busy, offline, onSend, onNewConversation }: ChatPanelProps) {
  const [text, setText] = useState('')
  const listRef = useRef<HTMLUListElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const disabled = busy || offline
  const trimmed = text.trim()
  const canSend = !disabled && trimmed.length > 0 && text.length <= MAX_MESSAGE_CHARS

  useEffect(() => {
    const el = listRef.current
    if (el) el.scrollTo?.({ top: el.scrollHeight, behavior: 'smooth' })
  }, [entries.length, busy])

  useLayoutEffect(() => {
    const el = inputRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 120)}px`
  }, [text])

  async function submit(value: string) {
    if (disabled || !value.trim()) return
    const typed = value === text // a suggestion sends text that was never in the box
    if (typed) setText('') // clear at once: the question is in the conversation now
    const accepted = await onSend(value)
    if (!accepted && typed) setText(value) // not sent (offline, too long): give it back
    inputRef.current?.focus()
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault()
    void submit(text)
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault()
      void submit(text)
    }
  }

  const placeholder = offline ? 'Fit AI Core offline…' : busy ? 'Aguarde a resposta…' : 'Pergunte algo sobre o carro'

  return (
    <section data-testid="chat-panel" aria-label="Conversa com o Fit AI" className="flex h-full min-h-0 flex-col bg-base-raised">
      <header className="flex items-center justify-between gap-2 px-5 pt-4">
        <h2 className="m-0 text-[14px] font-semibold text-ink-soft">Conversa</h2>
        {entries.length > 0 && (
          <button type="button" data-testid="new-conversation" disabled={busy} onClick={onNewConversation} className="-my-2 min-h-[44px] rounded-full px-3 text-[13px] text-ink-dim transition hover:text-ink-soft disabled:opacity-40">
            Nova conversa
          </button>
        )}
      </header>

      <ul ref={listRef} data-testid="chat-list" aria-live="polite" className="hud-scroll m-0 flex min-h-0 flex-1 list-none flex-col gap-5 overflow-y-auto px-5 py-4">
        {entries.map((e) => (
          <MessageBubble key={e.id} entry={e} />
        ))}
        {busy && (
          <li data-testid="thinking-indicator" aria-label="O Fit AI está pensando" className="flex gap-1.5 py-2">
            {[0, 1, 2].map((i) => (
              <span key={i} aria-hidden className="h-1.5 w-1.5 rounded-full bg-ink-dim" style={{ animation: `blink 1.1s ease-in-out ${i * 0.18}s infinite` }} />
            ))}
          </li>
        )}
      </ul>

      <div className="px-5 pb-5 pt-2">
        {entries.length === 0 && !busy && (
          <div className="hud-scroll mb-3 flex gap-2 overflow-x-auto pb-1" data-testid="suggestions">
            {SUGGESTIONS.map((s) => (
              <button
                key={s}
                type="button"
                disabled={disabled}
                onClick={() => void submit(s)}
                className="min-h-[44px] shrink-0 whitespace-nowrap rounded-full bg-base-lift px-4 text-[14px] text-ink-soft transition hover:text-ink disabled:cursor-not-allowed disabled:opacity-40"
              >
                {s}
              </button>
            ))}
          </div>
        )}
        <form onSubmit={onSubmit} className="flex items-end gap-2.5">
          <label htmlFor="chat-input" className="sr-only">
            Mensagem para o Fit AI
          </label>
          <textarea
            id="chat-input"
            ref={inputRef}
            data-testid="chat-input"
            rows={1}
            value={text}
            maxLength={MAX_MESSAGE_CHARS}
            disabled={disabled}
            placeholder={placeholder}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={onKeyDown}
            className="max-h-[120px] min-h-[52px] flex-1 resize-none rounded-[26px] border border-transparent bg-base-lift px-5 py-3.5 text-[16px] text-ink placeholder:text-ink-dim focus:border-fit-orange/70 focus:outline-none disabled:cursor-not-allowed disabled:opacity-50"
          />
          <button
            type="submit"
            data-testid="chat-send"
            disabled={!canSend}
            aria-label="Enviar mensagem"
            className="grid h-[52px] w-[52px] shrink-0 place-items-center rounded-full bg-fit-orange text-base transition hover:bg-fit-amber disabled:cursor-not-allowed disabled:bg-base-lift disabled:text-ink-dim"
          >
            <svg aria-hidden width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M4 10h11M10.5 4.5 16 10l-5.5 5.5" />
            </svg>
          </button>
        </form>
        {text.length > MAX_MESSAGE_CHARS * 0.8 && (
          <div className="mt-1.5 text-right">
            <StatusBadge label={`${text.length}/${MAX_MESSAGE_CHARS}`} tone={text.length >= MAX_MESSAGE_CHARS ? 'error' : 'warn'} />
          </div>
        )}
      </div>
    </section>
  )
}
