/**
 * Audio math for the voice input: nothing here touches a microphone, the network or the DOM, so all of it is unit-testable.
 *
 * The browser captures at the sound card's rate (usually 48 000 Hz, sometimes 44 100 Hz) as 32-bit float. The Core accepts only
 * 16 kHz mono 16-bit PCM in a WAV container, so the UI converts explicitly: a proper low-pass + resample (never "keep every third
 * sample", which aliases, and never relabel the header, which changes the speed of the voice) and a canonical 44-byte header.
 */

export const TARGET_RATE = 16_000

/** Windowed-sinc kernel half-width in output-rate zero crossings: 16 is far more than speech needs and still cheap. */
const KERNEL_LOBES = 16
const KERNEL_RES = 256 // table steps per input sample

/** Concatenate captured blocks into one buffer. */
export function concatChunks(chunks: readonly Float32Array[]): Float32Array {
  let total = 0
  for (const c of chunks) total += c.length
  const out = new Float32Array(total)
  let at = 0
  for (const c of chunks) {
    out.set(c, at)
    at += c.length
  }
  return out
}

const sinc = (x: number) => (x === 0 ? 1 : Math.sin(Math.PI * x) / (Math.PI * x))
/** Blackman window over [-1, 1]. */
const blackman = (t: number) => (Math.abs(t) >= 1 ? 0 : 0.42 + 0.5 * Math.cos(Math.PI * t) + 0.08 * Math.cos(2 * Math.PI * t))

/**
 * Band-limited resampling by windowed-sinc interpolation. When the rate goes down, the sinc cutoff is lowered to the new Nyquist, so
 * what the target rate cannot represent (e.g. a 10 kHz tone going to 16 kHz) is removed instead of folding back as a false tone.
 * The output has exactly round(length * to / from) samples, so the duration (and therefore the pitch and speed) is preserved.
 */
export function resample(input: Float32Array, from: number, to: number = TARGET_RATE): Float32Array {
  if (!(from > 0) || !(to > 0)) throw new RangeError('sample rates must be positive')
  if (from === to) return input.slice()
  const ratio = from / to // input samples per output sample
  const outLength = Math.round((input.length * to) / from)
  const out = new Float32Array(outLength)
  const cutoff = Math.min(1, to / from) // relative to the input rate's Nyquist
  const half = Math.ceil(KERNEL_LOBES / cutoff) // kernel half-width in INPUT samples
  const last = input.length - 1
  // The kernel is tabulated once (1/256-sample steps, error far below 16-bit resolution): calling sin/cos for ~100 taps per output
  // sample would cost seconds for a 20 s utterance, the table makes it a few hundred milliseconds.
  const table = new Float32Array(2 * half * KERNEL_RES + 1)
  for (let j = 0; j < table.length; j++) {
    const d = j / KERNEL_RES - half
    table[j] = cutoff * sinc(d * cutoff) * blackman(d / half)
  }
  for (let i = 0; i < outLength; i++) {
    const centre = i * ratio
    const lo = Math.max(0, Math.ceil(centre - half))
    const hi = Math.min(last, Math.floor(centre + half))
    let acc = 0
    let norm = 0
    for (let k = lo; k <= hi; k++) {
      const w = table[Math.round((centre - k + half) * KERNEL_RES)] as number
      acc += (input[k] as number) * w
      norm += w
    }
    out[i] = norm !== 0 ? acc / norm : 0 // normalising keeps the gain at 1 near the edges where the kernel is cut by the buffer end
  }
  return out
}

/** float [-1, 1] to 16-bit signed, clipped (never wrapped). */
export function floatToInt16(input: Float32Array): Int16Array {
  const out = new Int16Array(input.length)
  for (let i = 0; i < input.length; i++) {
    const v = Math.max(-1, Math.min(1, input[i] as number))
    out[i] = v < 0 ? Math.round(v * 32768) : Math.round(v * 32767)
  }
  return out
}

/** Canonical RIFF/WAVE, PCM, mono, 16-bit, little-endian: exactly what the Core's strict parser accepts. */
export function encodeWav(samples: Int16Array, sampleRate: number = TARGET_RATE): Uint8Array {
  const dataBytes = samples.length * 2
  const buffer = new ArrayBuffer(44 + dataBytes)
  const v = new DataView(buffer)
  const tag = (at: number, s: string) => {
    for (let i = 0; i < s.length; i++) v.setUint8(at + i, s.charCodeAt(i))
  }
  tag(0, 'RIFF')
  v.setUint32(4, 36 + dataBytes, true)
  tag(8, 'WAVE')
  tag(12, 'fmt ')
  v.setUint32(16, 16, true) // fmt chunk size
  v.setUint16(20, 1, true) // PCM
  v.setUint16(22, 1, true) // mono
  v.setUint32(24, sampleRate, true)
  v.setUint32(28, sampleRate * 2, true) // byte rate
  v.setUint16(32, 2, true) // block align
  v.setUint16(34, 16, true) // bits per sample
  tag(36, 'data')
  v.setUint32(40, dataBytes, true)
  for (let i = 0; i < samples.length; i++) v.setInt16(44 + i * 2, samples[i] as number, true)
  return new Uint8Array(buffer)
}

/** Whole pipeline: what the microphone captured (any rate, float) to the request body for the Core. */
export function toWav16k(samples: Float32Array, sampleRate: number): Uint8Array {
  return encodeWav(floatToInt16(resample(samples, sampleRate, TARGET_RATE)), TARGET_RATE)
}

export function rms(samples: Float32Array): number {
  if (samples.length === 0) return 0
  let s = 0
  for (let i = 0; i < samples.length; i++) s += (samples[i] as number) ** 2
  return Math.sqrt(s / samples.length)
}

/**
 * Map a block's RMS to a 0..1 display level on a decibel scale (speech sits roughly between -45 and -15 dBFS; a linear map would
 * make normal speech look like silence). Silence and the noise floor map to 0.
 */
export function displayLevel(blockRms: number): number {
  if (!(blockRms > 0)) return 0
  const db = 20 * Math.log10(blockRms)
  return Math.max(0, Math.min(1, (db + 55) / 40))
}
