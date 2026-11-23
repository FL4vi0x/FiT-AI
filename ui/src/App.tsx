import { useMemo } from 'react'
import { createApi, type FitAiApi } from './api/client'
import { AnimatedGridBackground } from './components/AnimatedGridBackground'
import { ChatPanel } from './components/ChatPanel'
import { TopSystemBar } from './components/TopSystemBar'
import { VehicleStage } from './components/VehicleStage'
import { ageSeconds, fmtAge, parseTimestamp, STALE_AFTER_S } from './lib/format'
import { useFitAi, type UseFitAiOptions } from './state/useFitAi'
import { useNow } from './state/useNow'

const TEXT_BTN = 'min-h-[44px] rounded-full px-3 text-[14px] text-ink-dim transition hover:text-ink disabled:cursor-not-allowed disabled:opacity-40'

export interface AppProps {
  /** Injected in tests; the app talks to the same-origin proxy by default. */
  api?: FitAiApi
  options?: UseFitAiOptions
}

export default function App({ api, options }: AppProps) {
  const client = useMemo(() => api ?? createApi(), [api])
  const { state, derived, sendMessage, scanTelemetry, clearPresentation, setLive, newConversation } = useFitAi(client, options)
  const nowMs = useNow(1000)

  const offline = derived.mode === 'offline'
  const scanning = derived.mode === 'scanning'
  const hasProjection = state.telemetry.phase !== 'idle' || state.glance
  const ready = state.telemetry.phase === 'ready' ? state.telemetry : null

  // ONE line says where every number on the car comes from and how old it is (instead of a badge per number)
  let provenance: { text: string; stale: boolean } | null = null
  if (ready) {
    const age = ageSeconds(parseTimestamp(ready.reading.timestamp, ready.at), nowMs)
    const stale = age > STALE_AFTER_S
    const origin = ready.reading.simulated === true ? 'Simulado' : ready.reading.simulated === false ? 'Dados reais' : 'Origem não informada'
    provenance = { text: stale ? `${origin} · leitura desatualizada · ${fmtAge(age)}` : `${origin} · lido ${fmtAge(age)}`, stale }
  }

  return (
    <div className="relative flex h-full flex-col overflow-hidden" data-testid="app" data-mode={derived.mode}>
      <AnimatedGridBackground />
      <TopSystemBar core={state.core} octave={state.octave} ollama={state.ollama} nowMs={nowMs} feed={state.feed} />

      {/* side by side from 1280 px; below that the stage keeps the full width */}
      <main className="relative z-10 grid min-h-0 flex-1 grid-cols-1 grid-rows-[minmax(0,1.2fr)_minmax(0,1fr)] xl:grid-cols-[minmax(0,1fr)_24rem] xl:grid-rows-1 2xl:grid-cols-[minmax(0,1fr)_27rem]">
        <section aria-label="Veículo" className="relative min-h-0 min-w-0">
          <VehicleStage derived={derived} state={state} nowMs={nowMs} />

          <div className="absolute right-5 top-1 z-20">
            <button
              type="button"
              disabled={offline || scanning || state.chat.busy}
              onClick={() => void scanTelemetry('manual')}
              data-testid="scan-button"
              className="min-h-[44px] rounded-full border border-white/[0.14] px-5 text-[14px] text-ink-soft transition hover:border-fit-orange/60 hover:text-ink disabled:cursor-not-allowed disabled:opacity-40"
            >
              {scanning ? 'Consultando…' : 'Escanear veículo'}
            </button>
          </div>

          {hasProjection && !offline && (
            <div className="absolute left-5 top-1 z-20 flex flex-wrap items-center gap-x-2" data-testid="provenance">
              {provenance && (
                <span data-testid="provenance-text" className={`mr-2 text-[14px] ${provenance.stale ? 'text-warn' : 'text-ink-dim'}`}>
                  {provenance.text}
                </span>
              )}
              {ready && (
                <button type="button" className={`${TEXT_BTN} ${state.live ? 'text-fit-gold' : ''}`} aria-pressed={state.live} onClick={() => setLive(!state.live)} data-testid="live-button" title="Atualiza a leitura a cada 2 s, enquanto ela estiver na tela.">
                  {state.live ? 'Ao vivo · ligado' : 'Ao vivo'}
                </button>
              )}
              <button type="button" className={TEXT_BTN} onClick={clearPresentation} data-testid="clear-button">
                Limpar
              </button>
            </div>
          )}
        </section>

        <aside className="relative min-h-0">
          <ChatPanel entries={state.chat.entries} busy={state.chat.busy} offline={offline} onSend={sendMessage} onNewConversation={newConversation} />
        </aside>
      </main>
    </div>
  )
}
