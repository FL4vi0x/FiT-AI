import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, NetworkError, RequestAborted, type FitAiApi } from '../api/client'
import type { TranscribeResponse } from '../api/types'
import { MicUnsupported } from './capture'
import { AVAILABLE, deferred, domError, FakeMic, makeApi, OK_TRANSCRIPT, toneAudio } from './testkit'
import { useVoiceInput, type VoiceInputOptions } from './useVoiceInput'

let clockNow = 0
const clock = () => clockNow
const HOLD = 800 // ms: a real hold, longer than a tap

function setup(over: Partial<VoiceInputOptions> & { api?: FitAiApi; mic?: FakeMic } = {}) {
  const mic = over.mic ?? new FakeMic()
  const api = over.api ?? makeApi()
  clockNow = 0
  const hook = renderHook((props: Partial<VoiceInputOptions>) => useVoiceInput({ enabled: true, api, mic, clock, holdResultMs: 5_000, ...over, ...props }), { initialProps: {} })
  return { mic, api, ...hook }
}

/** press, wait the permission/open, hold, release: the whole push-to-talk gesture */
async function speak(h: ReturnType<typeof setup>, ms = HOLD) {
  act(() => h.result.current.press())
  await waitFor(() => expect(h.result.current.phase).toBe('listening'))
  clockNow += ms
  act(() => h.result.current.release())
}

afterEach(() => vi.restoreAllMocks())

describe('push-to-talk', () => {
  it('rests with the microphone closed: nothing is opened until a gesture', async () => {
    const h = setup()
    await waitFor(() => expect(h.result.current.availability).toBe('available'))
    expect(h.result.current.phase).toBe('idle')
    expect(h.mic.opens).toBe(0)
    expect(h.api.transcribe).not.toHaveBeenCalled()
  })

  it('hold, speak, release: listens, then transcribes with the microphone already released', async () => {
    const h = setup()
    act(() => h.result.current.press())
    expect(h.result.current.phase).toBe('permission_requested')
    await waitFor(() => expect(h.result.current.phase).toBe('listening'))
    expect(h.mic.opens).toBe(1)
    clockNow += HOLD
    act(() => h.result.current.release())
    await waitFor(() => expect(h.result.current.phase).toBe('completed'))
    const s = h.mic.last
    expect(s.stopCalls).toBe(1)
    expect(s.released).toBe(true) // the tracks were released
    expect(h.result.current.transcript).toBe(OK_TRANSCRIPT.text)
    // the request is a real 16 kHz mono WAV, resampled from the 48 kHz capture, with the same duration
    const wav = (h.api.transcribe as ReturnType<typeof vi.fn>).mock.calls[0]![0] as Uint8Array
    const v = new DataView(wav.buffer, wav.byteOffset)
    expect([v.getUint32(24, true), v.getUint16(22, true), v.getUint16(34, true)]).toEqual([16000, 1, 16])
    expect(v.getUint32(40, true)).toBe(16000 * 2) // 1 s
  })

  it('the transcript is never sent to the chat or anywhere else', async () => {
    const h = setup()
    await speak(h)
    await waitFor(() => expect(h.result.current.phase).toBe('completed'))
    expect(h.api.chat).not.toHaveBeenCalled()
    expect(h.api.transcribe).toHaveBeenCalledTimes(1)
  })

  it('the microphone is released BEFORE the phase becomes transcribing', async () => {
    const answer = deferred<TranscribeResponse>()
    const api = makeApi({ transcribe: vi.fn().mockReturnValue(answer.promise) })
    const h = setup({ api })
    await speak(h)
    await waitFor(() => expect(h.result.current.phase).toBe('transcribing'))
    expect(h.mic.last.released).toBe(true)
    expect(h.mic.last.cancelCalls + h.mic.last.stopCalls).toBeGreaterThan(0)
    answer.resolve(OK_TRANSCRIPT)
    await waitFor(() => expect(h.result.current.phase).toBe('completed'))
  })

  it('feeds the level meter only while listening, and flattens it when the microphone is off', async () => {
    const answer = deferred<TranscribeResponse>()
    const h = setup({ api: makeApi({ transcribe: vi.fn().mockReturnValue(answer.promise) }) })
    h.mic.manual = false
    act(() => h.result.current.press())
    await waitFor(() => expect(h.result.current.phase).toBe('listening'))
    act(() => h.mic.last.level(0.1)) // speech-level RMS
    expect(h.result.current.meter.current()).toBeGreaterThan(0.3)
    clockNow += HOLD
    act(() => h.result.current.release())
    await waitFor(() => expect(h.result.current.phase).toBe('transcribing'))
    expect(h.result.current.meter.current()).toBe(0) // transcribing: bars must not react to the microphone
    act(() => h.mic.last.level(0.5)) // a late block from the closed microphone
    expect(h.result.current.meter.current()).toBe(0)
    answer.resolve(OK_TRANSCRIPT)
    await waitFor(() => expect(h.result.current.phase).toBe('completed'))
  })

  it('returns to rest after showing the result', async () => {
    const h = setup({ holdResultMs: 60 })
    await speak(h)
    await waitFor(() => expect(h.result.current.phase).toBe('completed'))
    await waitFor(() => expect(h.result.current.phase).toBe('idle'))
    expect(h.result.current.transcript).toBeNull()
  })

  it('a quick tap listens until the next tap (the accessible alternative to holding)', async () => {
    const h = setup()
    await speak(h, 100) // released after 100 ms: a tap, not a hold
    expect(h.result.current.phase).toBe('listening') // still open
    expect(h.api.transcribe).not.toHaveBeenCalled()
    clockNow += 2000
    act(() => h.result.current.press()) // second tap
    await waitFor(() => expect(h.result.current.phase).toBe('completed'))
    expect(h.mic.opens).toBe(1)
  })

  it('toggle() (a click from assistive technology) starts, and stops', async () => {
    const h = setup()
    act(() => h.result.current.toggle())
    await waitFor(() => expect(h.result.current.phase).toBe('listening'))
    act(() => h.result.current.toggle())
    await waitFor(() => expect(h.result.current.phase).toBe('completed'))
  })

  it('never runs two captures at once', async () => {
    const h = setup()
    act(() => {
      h.result.current.press()
      h.result.current.press()
      h.result.current.toggle()
    })
    await waitFor(() => expect(h.result.current.phase).toBe('listening'))
    expect(h.mic.opens).toBe(1)
    expect(h.mic.sessions).toHaveLength(1)
  })

  it('a too-short recording is refused locally, without any request', async () => {
    const mic = new FakeMic()
    mic.audio = toneAudio(0.1)
    const h = setup({ mic })
    await speak(h)
    await waitFor(() => expect(h.result.current.error).toBe('too_short'))
    expect(h.api.transcribe).not.toHaveBeenCalled()
    expect(h.mic.last.released).toBe(true)
  })

  it('reaching the maximum duration stops and transcribes by itself', async () => {
    const h = setup()
    act(() => h.result.current.press())
    await waitFor(() => expect(h.result.current.phase).toBe('listening'))
    act(() => h.mic.last.end('max_duration'))
    await waitFor(() => expect(h.result.current.phase).toBe('completed'))
    expect(h.mic.last.stopCalls).toBe(1)
  })
})

describe('microphone errors', () => {
  it.each([
    [domError('NotAllowedError'), 'permission_denied'],
    [domError('SecurityError'), 'permission_denied'],
    [domError('NotFoundError'), 'no_microphone'],
    [domError('OverconstrainedError'), 'no_microphone'],
    [domError('NotReadableError'), 'device_busy'],
    [domError('AbortError'), 'device_busy'],
    [new MicUnsupported(), 'unsupported'],
    [domError('SomethingElse'), 'capture_failed'],
  ])('%s becomes %s, with no audio and no request', async (error, code) => {
    const mic = new FakeMic()
    mic.rejectWith = error
    const h = setup({ mic, holdResultMs: 120 })
    act(() => h.result.current.press())
    await waitFor(() => expect(h.result.current.phase).toBe('error'))
    expect(h.result.current.error).toBe(code)
    expect(h.api.transcribe).not.toHaveBeenCalled()
    await waitFor(() => expect(h.result.current.phase).toBe('idle')) // and it can be tried again
  })

  it('a device unplugged while listening ends the capture with an error and no request', async () => {
    const h = setup()
    act(() => h.result.current.press())
    await waitFor(() => expect(h.result.current.phase).toBe('listening'))
    act(() => h.mic.last.end('device_lost'))
    await waitFor(() => expect(h.result.current.error).toBe('device_lost'))
    expect(h.mic.last.released).toBe(true)
    expect(h.api.transcribe).not.toHaveBeenCalled()
  })
})

describe('cancelling and races', () => {
  it('cancel while listening discards the audio: nothing is sent', async () => {
    const h = setup()
    act(() => h.result.current.press())
    await waitFor(() => expect(h.result.current.phase).toBe('listening'))
    act(() => h.result.current.cancel())
    expect(h.result.current.phase).toBe('cancelled')
    expect(h.mic.last.released).toBe(true)
    expect(h.api.transcribe).not.toHaveBeenCalled()
    expect(h.result.current.meter.current()).toBe(0)
  })

  it('Escape cancels', async () => {
    const h = setup()
    act(() => h.result.current.press())
    await waitFor(() => expect(h.result.current.phase).toBe('listening'))
    act(() => void window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' })))
    expect(h.result.current.phase).toBe('cancelled')
    expect(h.result.current.cancelledBecause).toBe('user')
  })

  it('losing focus while listening cancels (a missed key-up must never leave the microphone open)', async () => {
    const h = setup()
    act(() => h.result.current.press())
    await waitFor(() => expect(h.result.current.phase).toBe('listening'))
    act(() => void window.dispatchEvent(new Event('blur')))
    expect(h.result.current.phase).toBe('cancelled')
    expect(h.result.current.cancelledBecause).toBe('focus_lost')
    expect(h.mic.last.released).toBe(true)
  })

  it('the tab being hidden cancels', async () => {
    const h = setup()
    act(() => h.result.current.press())
    await waitFor(() => expect(h.result.current.phase).toBe('listening'))
    vi.spyOn(document, 'hidden', 'get').mockReturnValue(true)
    act(() => void document.dispatchEvent(new Event('visibilitychange')))
    expect(h.result.current.phase).toBe('cancelled')
  })

  it('navigating away (hashchange) cancels', async () => {
    const h = setup()
    act(() => h.result.current.press())
    await waitFor(() => expect(h.result.current.phase).toBe('listening'))
    act(() => void window.dispatchEvent(new HashChangeEvent('hashchange')))
    expect(h.result.current.cancelledBecause).toBe('navigation')
    expect(h.mic.last.released).toBe(true)
  })

  it('a blur while the permission prompt is open does NOT cancel (the prompt itself can take the focus)', async () => {
    const mic = new FakeMic()
    mic.manual = true
    const h = setup({ mic })
    act(() => h.result.current.press())
    act(() => void window.dispatchEvent(new Event('blur')))
    expect(h.result.current.phase).toBe('permission_requested')
    act(() => void mic.grantNext())
    await waitFor(() => expect(h.result.current.phase).toBe('listening'))
  })

  it('a permission granted AFTER the session was cancelled is released at once and never listens', async () => {
    const mic = new FakeMic()
    mic.manual = true
    const h = setup({ mic })
    act(() => h.result.current.press())
    expect(h.result.current.phase).toBe('permission_requested')
    act(() => h.result.current.cancel())
    const late = mic.grantNext() // the user clicks "Allow" after cancelling
    await waitFor(() => expect(late.cancelCalls).toBe(1))
    expect(late.released).toBe(true)
    expect(h.result.current.phase).not.toBe('listening')
    expect(h.api.transcribe).not.toHaveBeenCalled()
  })

  it('letting go while the permission prompt is still open cancels instead of listening later', async () => {
    const mic = new FakeMic()
    mic.manual = true
    const h = setup({ mic })
    act(() => h.result.current.press())
    clockNow += HOLD
    act(() => h.result.current.release())
    expect(h.result.current.phase).toBe('cancelled')
    const late = mic.grantNext()
    await waitFor(() => expect(late.released).toBe(true))
    expect(h.result.current.phase).not.toBe('listening')
  })

  it('a late permission DENIAL of a cancelled session does not show an error', async () => {
    const mic = new FakeMic()
    mic.manual = true
    const h = setup({ mic })
    act(() => h.result.current.press())
    act(() => h.result.current.cancel())
    mic.denyNext(domError('NotAllowedError'))
    await new Promise((r) => setTimeout(r, 20))
    expect(h.result.current.phase).toBe('cancelled')
    expect(h.result.current.error).toBeNull()
  })

  it('cancelling while transcribing aborts the request and ignores the late answer', async () => {
    const answer = deferred<TranscribeResponse>()
    let signal: AbortSignal | undefined
    const api = makeApi({ transcribe: vi.fn((_w: Uint8Array, s?: AbortSignal) => ((signal = s), answer.promise)) })
    const h = setup({ api })
    await speak(h)
    await waitFor(() => expect(h.result.current.phase).toBe('transcribing'))
    act(() => h.result.current.cancel())
    expect(signal?.aborted).toBe(true)
    answer.resolve({ ...OK_TRANSCRIPT, text: 'resposta atrasada' }) // arrives after the cancel
    await new Promise((r) => setTimeout(r, 20))
    expect(h.result.current.phase).toBe('cancelled')
    expect(h.result.current.transcript).toBeNull()
  })

  it('an aborted request is not reported as an error', async () => {
    const api = makeApi({ transcribe: vi.fn().mockRejectedValue(new RequestAborted()) })
    const h = setup({ api })
    await speak(h)
    await new Promise((r) => setTimeout(r, 30))
    expect(h.result.current.error).toBeNull()
  })

  it('a late answer of the previous session never lands in the next one', async () => {
    const first = deferred<TranscribeResponse>()
    const api = makeApi({ transcribe: vi.fn().mockReturnValueOnce(first.promise).mockResolvedValue({ ...OK_TRANSCRIPT, text: 'segunda' }) })
    const h = setup({ api })
    await speak(h)
    await waitFor(() => expect(h.result.current.phase).toBe('transcribing'))
    act(() => h.result.current.cancel())
    expect(h.result.current.phase).toBe('cancelled')
    await speak(h) // a new session starts at once: a cancelled capture is a resting phase, nobody waits for it to clear
    await waitFor(() => expect(h.result.current.transcript).toBe('segunda'))
    first.resolve({ ...OK_TRANSCRIPT, text: 'primeira, atrasada' })
    await new Promise((r) => setTimeout(r, 30))
    expect(h.result.current.transcript).toBe('segunda')
  })

  it('unmounting while listening releases the microphone and sends nothing', async () => {
    const h = setup()
    act(() => h.result.current.press())
    await waitFor(() => expect(h.result.current.phase).toBe('listening'))
    const s = h.mic.last
    h.unmount()
    expect(s.released).toBe(true)
    expect(h.api.transcribe).not.toHaveBeenCalled()
  })

  it('unmounting while transcribing aborts the request', async () => {
    const answer = deferred<TranscribeResponse>()
    let signal: AbortSignal | undefined
    const h = setup({ api: makeApi({ transcribe: vi.fn((_w: Uint8Array, s?: AbortSignal) => ((signal = s), answer.promise)) }) })
    await speak(h)
    await waitFor(() => expect(h.result.current.phase).toBe('transcribing'))
    h.unmount()
    expect(signal?.aborted).toBe(true)
    answer.resolve(OK_TRANSCRIPT) // must not throw or update state after unmount
    await new Promise((r) => setTimeout(r, 20))
  })

  it('unmounting while the permission prompt is open releases a microphone granted later', async () => {
    const mic = new FakeMic()
    mic.manual = true
    const h = setup({ mic })
    act(() => h.result.current.press())
    h.unmount()
    const late = mic.grantNext()
    await waitFor(() => expect(late.released).toBe(true))
  })

  it('turning the feature off (leaving the active screen) cancels an ongoing capture', async () => {
    const h = setup()
    act(() => h.result.current.press())
    await waitFor(() => expect(h.result.current.phase).toBe('listening'))
    h.rerender({ enabled: false })
    expect(h.result.current.phase).toBe('cancelled')
    expect(h.result.current.cancelledBecause).toBe('disabled')
    expect(h.mic.last.released).toBe(true)
  })

  it('nothing starts while disabled', async () => {
    const h = setup({ enabled: false })
    act(() => h.result.current.press())
    act(() => h.result.current.toggle())
    expect(h.result.current.phase).toBe('idle')
    expect(h.mic.opens).toBe(0)
    expect(h.api.voiceStatus).not.toHaveBeenCalled() // and the Core is not asked anything
  })
})

describe('what the Core answers', () => {
  const failWith = (e: unknown) => makeApi({ transcribe: vi.fn().mockRejectedValue(e) })
  it.each([
    [new ApiError(503, 'stt_model_missing', 'm'), 'model_missing'],
    [new ApiError(503, 'stt_unavailable', 'm'), 'stt_unavailable'],
    [new ApiError(503, 'stt_disabled', 'm'), 'stt_disabled'],
    [new ApiError(429, 'stt_busy', 'm'), 'stt_busy'],
    [new ApiError(504, 'stt_timeout', 'm'), 'stt_timeout'],
    [new ApiError(502, 'stt_failed', 'm'), 'stt_failed'],
    [new ApiError(403, 'origin_not_allowed', 'm'), 'origin_not_allowed'],
    [new ApiError(422, 'invalid_audio', 'm'), 'invalid_audio'],
    [new ApiError(422, 'audio_too_short', 'm'), 'too_short'],
    [new ApiError(413, 'payload_too_large', 'm'), 'invalid_audio'],
    [new ApiError(500, 'internal_error', 'm'), 'unknown'],
    [new NetworkError('offline', 'x'), 'core_offline'],
    [new NetworkError('timeout', 'x'), 'timeout'],
    [new Error('???'), 'unknown'],
  ])('%s -> %s', async (error, code) => {
    const h = setup({ api: failWith(error) })
    await speak(h)
    await waitFor(() => expect(h.result.current.error).toBe(code))
    expect(h.result.current.phase).toBe('error')
    expect(h.result.current.transcript).toBeNull()
  })

  it('"silent" and empty text are both "I heard nothing", not a transcript', async () => {
    for (const answer of [{ ...OK_TRANSCRIPT, text: '', silent: true }, { ...OK_TRANSCRIPT, text: '   ', silent: false }]) {
      const h = setup({ api: makeApi({ transcribe: vi.fn().mockResolvedValue(answer) }) })
      await speak(h)
      await waitFor(() => expect(h.result.current.error).toBe('no_speech'))
      h.unmount()
    }
  })

  it('a malformed answer does not crash the screen', async () => {
    const h = setup({ api: makeApi({ transcribe: vi.fn().mockResolvedValue(null as unknown as TranscribeResponse) }) })
    await speak(h)
    await waitFor(() => expect(h.result.current.error).toBe('no_speech'))
  })
})

describe('availability', () => {
  it('reports what the Core says, read-only', async () => {
    const api = makeApi({ voiceStatus: vi.fn().mockResolvedValue({ ...AVAILABLE, state: 'model_missing', hint: 'instale' }) })
    const h = setup({ api })
    await waitFor(() => expect(h.result.current.availability).toBe('model_missing'))
    expect(h.result.current.hint).toBe('instale')
    expect(h.mic.opens).toBe(0)
  })
  it('an unreachable Core is "unknown", and does not block the attempt', async () => {
    const h = setup({ api: makeApi({ voiceStatus: vi.fn().mockRejectedValue(new NetworkError('offline', 'x')) }) })
    await waitFor(() => expect(h.result.current.availability).toBe('unknown'))
    await speak(h)
    await waitFor(() => expect(h.result.current.phase).toBe('completed'))
  })
  it('a missing model discovered by a real attempt refreshes the availability', async () => {
    const voiceStatus = vi.fn().mockResolvedValueOnce(AVAILABLE).mockResolvedValue({ ...AVAILABLE, state: 'model_missing' })
    const h = setup({ api: makeApi({ voiceStatus, transcribe: vi.fn().mockRejectedValue(new ApiError(503, 'stt_model_missing', 'm')) }) })
    await waitFor(() => expect(h.result.current.availability).toBe('available'))
    await speak(h)
    await waitFor(() => expect(h.result.current.availability).toBe('model_missing'))
  })
})
