import { describe, expect, it, vi } from 'vitest'
import { classifyMicError, createBrowserMic, MicUnsupported, type BrowserMicEnv } from './capture'
import { domError } from './testkit'

class FakeTrack {
  stopped = false
  onended: (() => void) | null = null
  stop() {
    this.stopped = true
  }
}
class FakeStream {
  tracks = [new FakeTrack()]
  getTracks() {
    return this.tracks
  }
  getAudioTracks() {
    return this.tracks
  }
}
class FakePort {
  onmessage: ((e: MessageEvent) => void) | null = null
  posted: unknown[] = []
  postMessage(m: unknown) {
    this.posted.push(m)
    if (m === 'flush') queueMicrotask(() => this.emit({ pcm: new Float32Array([0.5, 0.5]) }, { flushed: true }))
  }
  emit(...messages: object[]) {
    for (const data of messages) this.onmessage?.({ data } as MessageEvent)
  }
}
class FakeNode {
  static last: FakeNode
  port = new FakePort()
  disconnected = false
  constructor() {
    FakeNode.last = this
  }
  connect() {}
  disconnect() {
    this.disconnected = true
  }
}
class FakeContext {
  static last: FakeContext
  state = 'running'
  sampleRate = 48000
  closed = false
  failModule = false
  destination = {}
  audioWorklet = { addModule: vi.fn(async () => { if (FakeContext.failModuleNext) throw new Error('blocked by CSP') }) }
  static failModuleNext = false
  constructor() {
    FakeContext.last = this
  }
  async resume() {}
  createMediaStreamSource() {
    return { connect() {}, disconnect() {} }
  }
  createGain() {
    return { gain: { value: 1 }, connect() {}, disconnect() {} }
  }
  async close() {
    this.closed = true
  }
}

function env(over: Partial<BrowserMicEnv> & { stream?: FakeStream; reject?: unknown } = {}) {
  const stream = over.stream ?? new FakeStream()
  const getUserMedia = vi.fn(async (_c: MediaStreamConstraints) => {
    if (over.reject) throw over.reject
    return stream as unknown as MediaStream
  })
  FakeContext.failModuleNext = false
  return {
    stream,
    getUserMedia,
    env: {
      mediaDevices: { getUserMedia },
      audioContext: FakeContext as unknown as typeof AudioContext,
      workletNode: FakeNode as unknown as typeof AudioWorkletNode,
      workletUrl: '/worklets/pcm-capture.js',
      ...over,
    } as BrowserMicEnv,
  }
}
const opts = () => ({ onLevel: vi.fn(), onEnded: vi.fn(), maxSeconds: 20 })

describe('classifyMicError', () => {
  it.each([
    ['NotAllowedError', 'permission_denied'], ['SecurityError', 'permission_denied'], ['PermissionDeniedError', 'permission_denied'],
    ['NotFoundError', 'no_microphone'], ['DevicesNotFoundError', 'no_microphone'], ['OverconstrainedError', 'no_microphone'],
    ['NotReadableError', 'device_busy'], ['TrackStartError', 'device_busy'], ['AbortError', 'device_busy'],
    ['TypeError', 'capture_failed'], ['', 'capture_failed'],
  ])('%s -> %s', (name, code) => expect(classifyMicError(domError(name))).toBe(code))
  it('handles non-errors', () => {
    expect(classifyMicError(new MicUnsupported())).toBe('unsupported')
    expect(classifyMicError(null)).toBe('capture_failed')
    expect(classifyMicError('boom')).toBe('capture_failed')
  })
})

describe('browser microphone', () => {
  it('asks for AUDIO ONLY, mono, and never video', async () => {
    const e = env()
    await createBrowserMic(e.env).open(opts())
    const constraints = e.getUserMedia.mock.calls[0]![0]
    expect(constraints.video).toBe(false)
    expect(constraints.audio).toMatchObject({ channelCount: 1 })
  })

  it('does not touch the microphone until open() is called', () => {
    const e = env()
    createBrowserMic(e.env)
    expect(e.getUserMedia).not.toHaveBeenCalled()
  })

  it('reports an unsupported platform (no mediaDevices: e.g. plain http on a non-loopback host)', async () => {
    await expect(createBrowserMic({ mediaDevices: undefined, audioContext: FakeContext as never, workletNode: FakeNode as never }).open(opts())).rejects.toBeInstanceOf(MicUnsupported)
    await expect(createBrowserMic({ mediaDevices: { getUserMedia: vi.fn() }, audioContext: undefined, workletNode: FakeNode as never }).open(opts())).rejects.toBeInstanceOf(MicUnsupported)
  })

  it('a denied permission opens nothing (no stream exists to leak)', async () => {
    const e = env({ reject: domError('NotAllowedError') })
    await expect(createBrowserMic(e.env).open(opts())).rejects.toMatchObject({ name: 'NotAllowedError' })
    expect(e.stream.tracks[0]!.stopped).toBe(false) // never opened
  })

  it('stop() releases every track, tears down the graph and returns the samples at the real rate', async () => {
    const e = env()
    const o = opts()
    const session = await createBrowserMic(e.env).open(o)
    const node = FakeNode.last
    node.port.emit({ pcm: new Float32Array([0.1, 0.2, 0.3]) }, { pcm: new Float32Array([0.4]) })
    expect(o.onLevel).toHaveBeenCalledTimes(2)
    const audio = await session.stop()
    expect(Array.from(audio.samples)).toEqual([expect.closeTo(0.1), expect.closeTo(0.2), expect.closeTo(0.3), expect.closeTo(0.4), 0.5, 0.5]) // incl. the flushed block
    expect(audio.sampleRate).toBe(48000)
    expect(e.stream.tracks[0]!.stopped).toBe(true)
    expect(node.disconnected).toBe(true)
    expect(FakeContext.last.closed).toBe(true)
  })

  it('cancel() releases everything and throws the audio away', async () => {
    const e = env()
    const session = await createBrowserMic(e.env).open(opts())
    FakeNode.last.port.emit({ pcm: new Float32Array([0.9]) })
    session.cancel()
    expect(e.stream.tracks[0]!.stopped).toBe(true)
    expect(FakeContext.last.closed).toBe(true)
    session.cancel() // idempotent
  })

  it('stop() after cancel() returns nothing', async () => {
    const e = env()
    const session = await createBrowserMic(e.env).open(opts())
    FakeNode.last.port.emit({ pcm: new Float32Array([0.9]) })
    session.cancel()
    expect((await session.stop()).samples.length).toBe(0)
  })

  it('a failure while building the audio graph still releases the microphone', async () => {
    const e = env()
    FakeContext.failModuleNext = true // e.g. the worklet is blocked
    class Failing extends FakeContext {
      constructor() {
        super()
        FakeContext.failModuleNext = true
      }
    }
    await expect(createBrowserMic({ ...e.env, audioContext: Failing as never }).open(opts())).rejects.toThrow('blocked by CSP')
    expect(e.stream.tracks[0]!.stopped).toBe(true) // the stream had been granted: it must not stay open
  })

  it('stops the tracks even if the worklet never answers the flush', async () => {
    vi.useFakeTimers()
    try {
      const e = env()
      const session = await createBrowserMic(e.env).open(opts())
      FakeNode.last.port.postMessage = () => {} // silent worklet
      const done = session.stop()
      await vi.advanceTimersByTimeAsync(500)
      await done
      expect(e.stream.tracks[0]!.stopped).toBe(true)
    } finally {
      vi.useRealTimers()
    }
  })

  it('a device that goes away (track ended) is reported', async () => {
    const e = env()
    const o = opts()
    await createBrowserMic(e.env).open(o)
    e.stream.tracks[0]!.onended?.()
    expect(o.onEnded).toHaveBeenCalledWith('device_lost')
  })

  it('reports the maximum duration once reached', async () => {
    const e = env()
    const o = { ...opts(), maxSeconds: 1 }
    await createBrowserMic(e.env).open(o)
    FakeNode.last.port.emit({ pcm: new Float32Array(48000) }) // exactly 1 s at 48 kHz
    expect(o.onEnded).toHaveBeenCalledWith('max_duration')
  })

  it('ignores blocks that arrive after release', async () => {
    const e = env()
    const o = opts()
    const session = await createBrowserMic(e.env).open(o)
    const node = FakeNode.last
    session.cancel()
    node.port.emit({ pcm: new Float32Array([1]) })
    expect(o.onLevel).not.toHaveBeenCalled()
  })
})
