import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ApiError, createApi, NetworkError, RequestAborted, type FitAiApi } from '../api/client'
import type { VoiceState } from '../api/types'
import { toWav16k } from './audio'
import { createBrowserMic, classifyMicError, type MicCapture, type MicSession } from './capture'
import { createLevelMeter, type LevelMeter } from './levels'
import { displayLevel } from './audio'
import { INITIAL_VOICE_STATE, isBusyPhase, voiceReducer, type CancelReason, type VoiceErrorCode, type VoiceEvent, type VoiceMachineState } from './voiceMachine'

export type VoiceAvailability = 'checking' | 'unknown' | VoiceState

export interface VoiceInputOptions {
  /** false: nothing can start, an active capture is cancelled, and the Core is not asked anything */
  enabled: boolean
  api?: FitAiApi
  mic?: MicCapture
  /** longest single recording; the Core accepts up to 30 s */
  maxSeconds?: number
  /** a press shorter than this is a tap: it starts listening and the NEXT tap stops it (the accessible alternative to holding) */
  tapMs?: number
  /** how long a result or an error stays on screen before the control returns to rest */
  holdResultMs?: number
  clock?: () => number
}

export interface VoiceInput extends VoiceMachineState {
  availability: VoiceAvailability
  /** the Core's own words for how to fix an unavailable engine */
  hint: string | null
  meter: LevelMeter
  /** pointer down / key down on the control */
  press(): void
  /** pointer up / key up on the control */
  release(): void
  /** a click that did not come from a press (assistive technology): starts, or stops */
  toggle(): void
  cancel(reason?: CancelReason): void
}

export const MAX_RECORDING_S = 20
export const MIN_RECORDING_S = 0.35
export const TAP_MS = 350
export const RESULT_HOLD_MS = 6_000
const CANCEL_HOLD_MS = 1_800

/** The Core's stable error codes (src/fit_ai/api/speech_routes.py and security.py) to what the UI says. Anything unknown is `unknown`. */
const CORE_ERROR: Readonly<Record<string, VoiceErrorCode>> = {
  stt_model_missing: 'model_missing',
  stt_unavailable: 'stt_unavailable',
  stt_disabled: 'stt_disabled',
  stt_busy: 'stt_busy',
  stt_timeout: 'stt_timeout',
  stt_failed: 'stt_failed',
  origin_not_allowed: 'origin_not_allowed',
  audio_too_short: 'too_short',
  audio_empty: 'invalid_audio',
  invalid_audio: 'invalid_audio',
  audio_too_long: 'invalid_audio',
  payload_too_large: 'invalid_audio',
  unsupported_media_type: 'invalid_audio',
}

export function mapApiError(e: unknown): VoiceErrorCode {
  if (e instanceof NetworkError) return e.kind === 'timeout' ? 'timeout' : 'core_offline'
  if (e instanceof ApiError) return CORE_ERROR[e.code] ?? 'unknown'
  return 'unknown'
}

/**
 * Push-to-talk. The microphone is opened ONLY by `press`/`toggle` (a user gesture), released the moment capture ends (stop, cancel, error,
 * focus loss, navigation, unmount), and the audio goes nowhere but the local Core's /voice/transcribe. The transcript is NOT sent to the chat.
 *
 * Races are handled by session number: every async continuation checks it still belongs to the current session before touching state,
 * and a microphone that was granted after its session was cancelled is released at once.
 */
export function useVoiceInput(options: VoiceInputOptions): VoiceInput {
  const { enabled, maxSeconds = MAX_RECORDING_S, tapMs = TAP_MS, holdResultMs = RESULT_HOLD_MS } = options
  const clock = options.clock ?? Date.now
  const apiRef = useRef<FitAiApi>(options.api ?? createApi())
  const micRef = useRef<MicCapture>(options.mic ?? createBrowserMic())
  const meter = useMemo(() => createLevelMeter(), [])

  const [state, setState] = useState<VoiceMachineState>(INITIAL_VOICE_STATE)
  const stateRef = useRef(state)
  const mounted = useRef(true)
  const counter = useRef(0) // session numbers, never reused
  const micSession = useRef<MicSession | null>(null)
  const abort = useRef<AbortController | null>(null)
  const resetTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const pressedAt = useRef(0)
  const toggleMode = useRef(false)
  const [availability, setAvailability] = useState<VoiceAvailability>('checking')
  const [hint, setHint] = useState<string | null>(null)

  const dispatch = useCallback((event: VoiceEvent) => {
    const next = voiceReducer(stateRef.current, event)
    if (next === stateRef.current) return
    stateRef.current = next
    if (mounted.current) setState(next)
  }, [])

  const current = (session: number) => stateRef.current.session === session
  const phaseNow = () => stateRef.current.phase // a call, so TypeScript never assumes the phase is the same after an await
  const clearResetTimer = () => {
    if (resetTimer.current) clearTimeout(resetTimer.current)
    resetTimer.current = null
  }
  const scheduleReset = useCallback(
    (session: number, ms: number) => {
      clearResetTimer()
      resetTimer.current = setTimeout(() => dispatch({ type: 'reset', session }), ms)
    },
    [dispatch],
  )

  /** Releases whatever is held and forgets it, WITHOUT touching state. */
  const dropResources = () => {
    micSession.current?.cancel()
    micSession.current = null
    abort.current?.abort()
    abort.current = null
    meter.reset()
  }

  const cancel = useCallback(
    (reason: CancelReason = 'user') => {
      if (!isBusyPhase(phaseNow())) return
      const next = ++counter.current // every in-flight result of the old session is stale from here on
      dropResources()
      toggleMode.current = false
      dispatch({ type: 'cancel', session: next, reason })
      scheduleReset(next, CANCEL_HOLD_MS)
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [dispatch, scheduleReset],
  )

  const fail = useCallback(
    (session: number, error: VoiceErrorCode) => {
      if (!current(session)) return
      dropResources()
      toggleMode.current = false
      dispatch({ type: 'failed', session, error })
      scheduleReset(session, holdResultMs)
      if (error === 'model_missing' || error === 'stt_unavailable' || error === 'stt_disabled') void refreshStatus()
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [dispatch, holdResultMs, scheduleReset],
  )

  const finish = useCallback(
    async (session: number) => {
      if (!current(session) || phaseNow() !== 'listening') return
      const mic = micSession.current
      micSession.current = null
      if (!mic) return
      let audio
      try {
        audio = await mic.stop() // the microphone is released before this resolves
      } catch {
        return fail(session, 'capture_failed')
      }
      if (!current(session)) return // cancelled while the last block was being collected: the audio is simply dropped
      dispatch({ type: 'stop', session })
      meter.reset() // from here the microphone is off and the bars must stop reacting to anything
      if (audio.samples.length / audio.sampleRate < MIN_RECORDING_S) return fail(session, 'too_short')

      let wav: Uint8Array
      try {
        wav = toWav16k(audio.samples, audio.sampleRate)
      } catch {
        return fail(session, 'invalid_audio')
      }
      const ctl = new AbortController()
      abort.current = ctl
      try {
        const result = await apiRef.current.transcribe(wav, ctl.signal)
        if (!current(session)) return // a late answer to a cancelled session is never used
        const text = typeof result?.text === 'string' ? result.text.trim() : ''
        if (result?.silent || text === '') return fail(session, 'no_speech')
        dispatch({ type: 'transcribed', session, text })
        scheduleReset(session, holdResultMs)
      } catch (e) {
        if (e instanceof RequestAborted || !current(session)) return
        fail(session, mapApiError(e))
      } finally {
        if (abort.current === ctl) abort.current = null
      }
    },
    [dispatch, fail, holdResultMs, scheduleReset],
  )

  const begin = useCallback(async () => {
    if (!enabled || isBusyPhase(phaseNow())) return // one capture at a time
    clearResetTimer()
    const session = ++counter.current
    meter.reset()
    dispatch({ type: 'start', session })
    let opened: MicSession
    try {
      opened = await micRef.current.open({
        maxSeconds,
        onLevel: (rms) => {
          if (current(session) && phaseNow() === 'listening') meter.push(displayLevel(rms))
        },
        onEnded: (why) => {
          if (!current(session) || phaseNow() !== 'listening') return
          if (why === 'max_duration') void finish(session)
          else fail(session, 'device_lost')
        },
      })
    } catch (e) {
      return fail(session, classifyMicError(e))
    }
    if (!current(session) || phaseNow() !== 'permission_requested') {
      opened.cancel() // granted after the session was cancelled or the screen was left: release it at once
      return
    }
    micSession.current = opened
    dispatch({ type: 'permission_granted', session })
  }, [dispatch, enabled, fail, finish, maxSeconds, meter])

  const press = useCallback(() => {
    const s = stateRef.current
    if (s.phase === 'listening' && toggleMode.current) {
      toggleMode.current = false
      void finish(s.session) // the second tap of tap-to-talk
      return
    }
    if (isBusyPhase(s.phase)) return
    pressedAt.current = clock()
    toggleMode.current = false
    void begin()
  }, [begin, clock, finish])

  const release = useCallback(() => {
    const s = stateRef.current
    if (toggleMode.current || (s.phase !== 'listening' && s.phase !== 'permission_requested')) return
    if (clock() - pressedAt.current < tapMs) {
      toggleMode.current = true // a tap: keep listening until tapped again (also what a switch or a screen reader can do)
    } else if (s.phase === 'listening') {
      void finish(s.session)
    } else {
      cancel('user') // let go while the browser's permission prompt was still open
    }
  }, [cancel, clock, finish, tapMs])

  const toggle = useCallback(() => {
    const s = stateRef.current
    if (s.phase === 'listening') {
      toggleMode.current = false
      void finish(s.session)
    } else if (!isBusyPhase(s.phase)) {
      toggleMode.current = true
      pressedAt.current = clock()
      void begin()
    }
  }, [begin, clock, finish])

  async function refreshStatus() {
    try {
      const r = await apiRef.current.voiceStatus()
      if (!mounted.current) return
      setAvailability(r?.state ?? 'unknown')
      setHint(r?.hint ?? null)
    } catch {
      if (mounted.current) setAvailability('unknown')
    }
  }

  // availability: asked once when the screen opens (read-only, never opens the microphone nor loads the model)
  useEffect(() => {
    if (!enabled) return
    setAvailability('checking')
    void refreshStatus()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled])

  // leaving the stage (Standby, Core offline) ends any capture
  useEffect(() => {
    if (!enabled) cancel('disabled')
  }, [enabled, cancel])

  // a push-to-talk key/pointer release can be missed when the window loses focus: never keep a microphone open in that case
  useEffect(() => {
    const onBlur = () => phaseNow() === 'listening' && cancel('focus_lost')
    const onHidden = () => document.hidden && cancel('focus_lost')
    const onNavigate = () => cancel('navigation')
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && cancel('user')
    window.addEventListener('blur', onBlur)
    document.addEventListener('visibilitychange', onHidden)
    window.addEventListener('hashchange', onNavigate)
    window.addEventListener('pagehide', onNavigate)
    window.addEventListener('keydown', onKey)
    return () => {
      window.removeEventListener('blur', onBlur)
      document.removeEventListener('visibilitychange', onHidden)
      window.removeEventListener('hashchange', onNavigate)
      window.removeEventListener('pagehide', onNavigate)
      window.removeEventListener('keydown', onKey)
    }
  }, [cancel])

  // unmounting releases the microphone and silences every late result
  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
      counter.current++
      stateRef.current = { ...stateRef.current, session: counter.current }
      clearResetTimer()
      dropResources()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return { ...state, availability, hint, meter, press, release, toggle, cancel }
}
