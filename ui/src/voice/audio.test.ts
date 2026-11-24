import { describe, expect, it } from 'vitest'
import { concatChunks, displayLevel, encodeWav, floatToInt16, resample, rms, TARGET_RATE, toWav16k } from './audio'

const tone = (hz: number, seconds: number, rate: number, amp = 0.5): Float32Array => {
  const out = new Float32Array(Math.round(seconds * rate))
  for (let i = 0; i < out.length; i++) out[i] = amp * Math.sin((2 * Math.PI * hz * i) / rate)
  return out
}
/** the middle of a buffer: the first and last few milliseconds of any filtered signal are a transient and not what is measured */
const middle = (x: Float32Array) => x.subarray(Math.floor(x.length * 0.1), Math.floor(x.length * 0.9))
const zeroCrossingsPerSecond = (x: Float32Array, rate: number) => {
  let n = 0
  for (let i = 1; i < x.length; i++) if ((x[i - 1] as number) < 0 && (x[i] as number) >= 0) n++
  return (n * rate) / x.length
}

describe('resample', () => {
  it.each([[48000], [44100], [32000], [22050], [8000], [96000]])('from %i Hz keeps the duration (so the speed of the voice)', (rate) => {
    const out = resample(tone(440, 2, rate), rate)
    expect(out.length).toBe(Math.round(2 * TARGET_RATE))
  })

  it('does nothing (but copy) at the target rate', () => {
    const x = tone(440, 0.1, TARGET_RATE)
    const y = resample(x, TARGET_RATE)
    expect(y).not.toBe(x)
    expect(Array.from(y)).toEqual(Array.from(x))
  })

  it.each([[48000], [44100], [32000]])('keeps the pitch of a 440 Hz tone captured at %i Hz (no fast/slow voice)', (rate) => {
    const out = resample(tone(440, 2, rate), rate)
    expect(zeroCrossingsPerSecond(middle(out), TARGET_RATE)).toBeGreaterThan(437)
    expect(zeroCrossingsPerSecond(middle(out), TARGET_RATE)).toBeLessThan(443)
  })

  it('keeps the level of speech-band content', () => {
    for (const hz of [300, 1000, 3000]) {
      const out = resample(tone(hz, 1, 48000, 0.5), 48000)
      expect(rms(middle(out)) / (0.5 / Math.SQRT2)).toBeGreaterThan(0.97)
      expect(rms(middle(out)) / (0.5 / Math.SQRT2)).toBeLessThan(1.03)
    }
  })

  it('removes what 16 kHz cannot represent instead of folding it into a false tone (anti-aliasing)', () => {
    // 10 kHz and 12 kHz are above the new 8 kHz Nyquist: a naive "take every third sample" would alias them to 6 kHz and 4 kHz
    for (const hz of [10000, 12000, 15000]) {
      const out = resample(tone(hz, 1, 48000, 0.5), 48000)
      expect(rms(middle(out)) / (0.5 / Math.SQRT2)).toBeLessThan(0.01) // at least 40 dB down
    }
    // and prove the claim above: decimating without filtering really does fold a 10 kHz tone into the speech band
    const x = tone(10000, 1, 48000, 0.5)
    const naive = new Float32Array(Math.floor(x.length / 3))
    for (let i = 0; i < naive.length; i++) naive[i] = x[i * 3] as number
    expect(rms(middle(naive))).toBeGreaterThan(0.3)
  })

  it('does not lose gain at the ends of the buffer', () => {
    const out = resample(new Float32Array(48000).fill(0.5), 48000)
    for (const i of [0, 1, 2, out.length - 3, out.length - 2, out.length - 1]) expect(out[i]).toBeCloseTo(0.5, 2)
  })

  it('handles empty and tiny inputs', () => {
    expect(resample(new Float32Array(0), 48000).length).toBe(0)
    expect(resample(new Float32Array([0.25]), 48000).length).toBe(0)
    expect(resample(new Float32Array([0.1, 0.2, 0.3, 0.4, 0.5, 0.6]), 48000).length).toBe(2)
  })

  it('rejects impossible rates', () => {
    expect(() => resample(new Float32Array(10), 0)).toThrow(RangeError)
    expect(() => resample(new Float32Array(10), 48000, -1)).toThrow(RangeError)
  })

  it('is fast enough for a 20 s utterance (kernel table, not sin/cos per tap)', () => {
    const x = tone(440, 20, 48000)
    const t = performance.now()
    resample(x, 48000)
    expect(performance.now() - t).toBeLessThan(2500) // generous for CI; typically a few hundred ms
  })
})

describe('floatToInt16', () => {
  it('maps full scale, zero and rounding', () => {
    expect(Array.from(floatToInt16(new Float32Array([0, 1, -1, 0.5, -0.5])))).toEqual([0, 32767, -32768, 16384, -16384])
  })
  it('clips instead of wrapping around', () => {
    expect(Array.from(floatToInt16(new Float32Array([1.5, -3, 100, -100])))).toEqual([32767, -32768, 32767, -32768])
  })
})

describe('encodeWav', () => {
  const parse = (b: Uint8Array) => {
    const v = new DataView(b.buffer, b.byteOffset, b.byteLength)
    const tag = (at: number) => String.fromCharCode(...b.subarray(at, at + 4))
    return {
      riff: tag(0), size: v.getUint32(4, true), wave: tag(8), fmt: tag(12), fmtSize: v.getUint32(16, true), format: v.getUint16(20, true),
      channels: v.getUint16(22, true), rate: v.getUint32(24, true), byteRate: v.getUint32(28, true), block: v.getUint16(32, true),
      bits: v.getUint16(34, true), data: tag(36), dataSize: v.getUint32(40, true),
      first: b.length >= 46 ? v.getInt16(44, true) : null, second: b.length >= 48 ? v.getInt16(46, true) : null,
    }
  }
  it('writes the canonical header the Core requires', () => {
    const wav = encodeWav(new Int16Array([1, -2, 300, -400]))
    const h = parse(wav)
    expect(h).toMatchObject({ riff: 'RIFF', wave: 'WAVE', fmt: 'fmt ', fmtSize: 16, format: 1, channels: 1, rate: 16000, byteRate: 32000, block: 2, bits: 16, data: 'data', dataSize: 8 })
    expect(h.size).toBe(wav.length - 8)
    expect(wav.length).toBe(44 + 8)
    expect([h.first, h.second]).toEqual([1, -2]) // little-endian, sign preserved
  })
  it('an empty recording still has a valid header', () => {
    expect(parse(encodeWav(new Int16Array(0))).dataSize).toBe(0)
  })
})

describe('toWav16k', () => {
  it('turns 48 kHz float capture into a 16 kHz PCM WAV of the same duration', () => {
    const wav = toWav16k(tone(440, 1.5, 48000), 48000)
    const v = new DataView(wav.buffer)
    expect(v.getUint32(24, true)).toBe(16000)
    expect(v.getUint32(40, true)).toBe(1.5 * 16000 * 2)
  })
  it('keeps the voice at the same pitch after the whole pipeline', () => {
    const wav = toWav16k(tone(440, 2, 44100), 44100)
    const pcm = new Int16Array(wav.buffer.slice(44))
    const f = new Float32Array(pcm.length)
    for (let i = 0; i < pcm.length; i++) f[i] = (pcm[i] as number) / 32768
    expect(zeroCrossingsPerSecond(middle(f), 16000)).toBeGreaterThan(437)
    expect(zeroCrossingsPerSecond(middle(f), 16000)).toBeLessThan(443)
  })
})

describe('helpers', () => {
  it('concatenates in order', () => {
    expect(Array.from(concatChunks([new Float32Array([1, 2]), new Float32Array([]), new Float32Array([3])]))).toEqual([1, 2, 3])
    expect(concatChunks([]).length).toBe(0)
  })
  it('rms', () => {
    expect(rms(new Float32Array(0))).toBe(0)
    expect(rms(new Float32Array([0.5, -0.5, 0.5, -0.5]))).toBeCloseTo(0.5)
  })
  it('displayLevel: silence is 0, normal speech is visible, loud is capped at 1, and it rises monotonically', () => {
    expect(displayLevel(0)).toBe(0)
    expect(displayLevel(NaN)).toBe(0)
    expect(displayLevel(0.0005)).toBe(0) // -66 dBFS noise floor
    expect(displayLevel(0.05)).toBeGreaterThan(0.4) // -26 dBFS, ordinary speech
    expect(displayLevel(0.9)).toBe(1)
    const a = [0.001, 0.005, 0.02, 0.05, 0.1, 0.3].map(displayLevel)
    expect([...a].sort((x, y) => x - y)).toEqual(a)
  })
})
