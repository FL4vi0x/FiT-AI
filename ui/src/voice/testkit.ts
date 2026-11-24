/** Test doubles for the voice input. Imported by tests only, never by the application. */
import { vi } from 'vitest'
import type { FitAiApi } from '../api/client'
import type { TranscribeResponse, VoiceStatusResponse } from '../api/types'
import type { EndedReason, MicCapture, MicOpenOptions, MicSession, RecordedAudio } from './capture'

/** `seconds` of a 440 Hz tone at `rate`: stands in for "the user spoke". Synthetic, never a recording. */
export function toneAudio(seconds = 1, rate = 48_000): RecordedAudio {
  const samples = new Float32Array(Math.round(seconds * rate))
  for (let i = 0; i < samples.length; i++) samples[i] = 0.3 * Math.sin((2 * Math.PI * 440 * i) / rate)
  return { samples, sampleRate: rate }
}

export class FakeSession implements MicSession {
  released = false
  stopCalls = 0
  cancelCalls = 0
  constructor(readonly options: MicOpenOptions, public audio: RecordedAudio = toneAudio(1)) {}
  async stop(): Promise<RecordedAudio> {
    this.stopCalls++
    this.released = true // a real session releases the tracks inside stop(), before it resolves
    return this.audio
  }
  cancel(): void {
    this.cancelCalls++
    this.released = true
  }
  level(rms: number): void {
    this.options.onLevel(rms)
  }
  end(reason: EndedReason): void {
    this.options.onEnded(reason)
  }
}

/** A microphone whose permission answer the test controls. */
export class FakeMic implements MicCapture {
  opens = 0
  sessions: FakeSession[] = []
  /** when set, `open` rejects with it at once (a denied / missing / busy device) */
  rejectWith: unknown = null
  /** when true, `open` waits for `grantNext()` / `denyNext()` (the browser's permission prompt is still open) */
  manual = false
  audio: RecordedAudio = toneAudio(1)
  private pending: { resolve(s: MicSession): void; reject(e: unknown): void; options: MicOpenOptions }[] = []

  open(options: MicOpenOptions): Promise<MicSession> {
    this.opens++
    if (this.rejectWith) return Promise.reject(this.rejectWith)
    if (this.manual) return new Promise((resolve, reject) => this.pending.push({ resolve, reject, options }))
    return Promise.resolve(this.make(options))
  }
  private make(options: MicOpenOptions): FakeSession {
    const s = new FakeSession(options, this.audio)
    this.sessions.push(s)
    return s
  }
  grantNext(): FakeSession {
    const p = this.pending.shift()
    if (!p) throw new Error('no permission prompt is pending')
    const s = this.make(p.options)
    p.resolve(s)
    return s
  }
  denyNext(error: unknown): void {
    this.pending.shift()?.reject(error)
  }
  get last(): FakeSession {
    return this.sessions[this.sessions.length - 1] as FakeSession
  }
}

export const domError = (name: string) => Object.assign(new Error(name), { name })

export const OK_TRANSCRIPT: TranscribeResponse = { text: 'qual é a velocidade do carro?', silent: false, duration_s: 1, processing_ms: 800, language: 'pt', model: 'faster-whisper-small' }
export const AVAILABLE: VoiceStatusResponse = { state: 'available', language: 'pt', max_audio_s: 30, sample_rate: 16000, hint: null }

export function makeApi(over: Partial<FitAiApi> = {}): FitAiApi {
  return {
    health: vi.fn(),
    status: vi.fn(),
    telemetry: vi.fn(),
    llmStatus: vi.fn(),
    chat: vi.fn(),
    voiceStatus: vi.fn().mockResolvedValue(AVAILABLE),
    transcribe: vi.fn().mockResolvedValue(OK_TRANSCRIPT),
    ...over,
  }
}

/** A promise settled by hand, to test answers that arrive late. */
export function deferred<T>() {
  let resolve!: (v: T) => void
  let reject!: (e: unknown) => void
  const promise = new Promise<T>((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

/** jsdom has no PointerEvent: without it `button` / `pointerId` would be missing from test events, unlike in a real browser. */
export function ensurePointerEvent(): void {
  if (typeof window.PointerEvent !== 'undefined') return
  class PointerEventPolyfill extends MouseEvent {
    readonly pointerId: number
    constructor(type: string, init: PointerEventInit = {}) {
      super(type, init)
      this.pointerId = init.pointerId ?? 0
    }
  }
  vi.stubGlobal('PointerEvent', PointerEventPolyfill)
}
