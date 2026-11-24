import { describe, expect, it } from 'vitest'
import { createLevelMeter } from './levels'
import { INITIAL_VOICE_STATE as I, voiceReducer as r, type VoiceEvent, type VoiceMachineState } from './voiceMachine'

const run = (events: VoiceEvent[], from: VoiceMachineState = I) => events.reduce(r, from)

describe('voice state machine', () => {
  it('walks the whole happy path in order', () => {
    expect(run([{ type: 'start', session: 1 }]).phase).toBe('permission_requested')
    expect(run([{ type: 'start', session: 1 }, { type: 'permission_granted', session: 1 }]).phase).toBe('listening')
    expect(run([{ type: 'start', session: 1 }, { type: 'permission_granted', session: 1 }, { type: 'stop', session: 1 }]).phase).toBe('transcribing')
    const done = run([{ type: 'start', session: 1 }, { type: 'permission_granted', session: 1 }, { type: 'stop', session: 1 }, { type: 'transcribed', session: 1, text: 'oi' }])
    expect(done).toMatchObject({ phase: 'completed', transcript: 'oi', error: null })
  })

  it('does not start a second capture while one is in progress (one microphone at a time)', () => {
    for (const phase of ['permission_requested', 'listening', 'transcribing'] as const) {
      const s = { ...I, phase, session: 3 }
      expect(r(s, { type: 'start', session: 4 })).toBe(s)
    }
  })

  it('can start again from any resting phase', () => {
    for (const phase of ['idle', 'completed', 'cancelled', 'error'] as const) {
      expect(r({ ...I, phase, session: 3, transcript: 'x' }, { type: 'start', session: 4 })).toMatchObject({ phase: 'permission_requested', session: 4, transcript: null, error: null })
    }
  })

  it('refuses steps out of order', () => {
    expect(r(I, { type: 'permission_granted', session: 0 })).toBe(I)
    expect(r(I, { type: 'stop', session: 0 })).toBe(I)
    const asking = run([{ type: 'start', session: 1 }])
    expect(r(asking, { type: 'stop', session: 1 })).toBe(asking) // not listening yet
    expect(r(asking, { type: 'transcribed', session: 1, text: 'x' })).toBe(asking) // nothing was transcribed
  })

  it('drops every event of a session that is not the current one (stale results)', () => {
    const listening = run([{ type: 'start', session: 5 }, { type: 'permission_granted', session: 5 }])
    for (const e of [
      { type: 'permission_granted', session: 4 }, { type: 'stop', session: 4 }, { type: 'transcribed', session: 4, text: 'late' },
      { type: 'failed', session: 4, error: 'stt_failed' }, { type: 'reset', session: 4 },
    ] as VoiceEvent[]) expect(r(listening, e)).toBe(listening)
  })

  it('a cancel moves to a NEW session, so what was in flight for the old one is stale', () => {
    const transcribing = run([{ type: 'start', session: 1 }, { type: 'permission_granted', session: 1 }, { type: 'stop', session: 1 }])
    const cancelled = r(transcribing, { type: 'cancel', session: 2, reason: 'user' })
    expect(cancelled).toMatchObject({ phase: 'cancelled', session: 2, cancelledBecause: 'user', transcript: null })
    // the answer of the cancelled session arrives afterwards: ignored
    expect(r(cancelled, { type: 'transcribed', session: 1, text: 'late' })).toBe(cancelled)
    expect(r(cancelled, { type: 'failed', session: 1, error: 'timeout' })).toBe(cancelled)
  })

  it('cancel does nothing at rest', () => {
    expect(r(I, { type: 'cancel', session: 1, reason: 'user' })).toBe(I)
    const done = { ...I, phase: 'completed' as const, transcript: 'x' }
    expect(r(done, { type: 'cancel', session: 1, reason: 'user' })).toBe(done)
  })

  it('an error ends the session with its code and no transcript', () => {
    const s = run([{ type: 'start', session: 1 }, { type: 'failed', session: 1, error: 'permission_denied' }])
    expect(s).toMatchObject({ phase: 'error', error: 'permission_denied', transcript: null })
  })

  it('reset returns to idle only from a finished phase of the same session', () => {
    const err = run([{ type: 'start', session: 1 }, { type: 'failed', session: 1, error: 'no_speech' }])
    expect(r(err, { type: 'reset', session: 1 })).toMatchObject({ phase: 'idle', error: null, transcript: null })
    expect(r(err, { type: 'reset', session: 2 })).toBe(err)
    const busy = run([{ type: 'start', session: 1 }])
    expect(r(busy, { type: 'reset', session: 1 })).toBe(busy) // never resets an in-progress capture
    expect(r(I, { type: 'reset', session: 0 })).toBe(I)
  })
})

describe('level meter', () => {
  it('starts flat, rises fast, falls slowly, and is flat again after reset', () => {
    const m = createLevelMeter(8)
    expect(m.current()).toBe(0)
    m.push(0.9)
    expect(m.current()).toBeCloseTo(0.9)
    m.push(0)
    expect(m.current()).toBeCloseTo(0.72) // release, not a cliff
    expect(m.history[1]).toBeCloseTo(0.9) // older values flow outwards
    m.reset()
    expect(Array.from(m.history).every((v) => v === 0)).toBe(true)
  })
  it('ignores garbage and clamps', () => {
    const m = createLevelMeter(4)
    m.push(NaN)
    m.push(Infinity)
    expect(m.current()).toBe(0)
    m.push(5)
    expect(m.current()).toBe(1)
    m.push(-3)
    expect(m.history[0]).toBeCloseTo(0.8)
  })
  it('never reallocates its history (readers keep the same array)', () => {
    const m = createLevelMeter(4)
    const h = m.history
    m.push(1)
    m.reset()
    expect(m.history).toBe(h)
  })
})
