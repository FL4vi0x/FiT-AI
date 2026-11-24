/**
 * Microphone capture. The ONLY place in the UI that asks the browser for the microphone, and only when `open()` is called, which only
 * happens from an explicit user gesture (see useVoiceInput). Nothing is recorded to disk, nothing leaves the page from here: the samples
 * stay in memory until the voice input converts them and sends them to the local Core.
 *
 * Audio only, default device. It uses an AudioWorklet (the modern, off-main-thread way; ScriptProcessorNode is deprecated) loaded from
 * the page's own origin, which the production CSP (`script-src 'self'`) allows.
 */
import { concatChunks, rms } from './audio'
import type { VoiceErrorCode } from './voiceMachine'

export interface RecordedAudio {
  samples: Float32Array
  /** the real rate of `samples` (the sound card's, usually 48 000 or 44 100): resampling is explicit and happens later */
  sampleRate: number
}

export type EndedReason = 'device_lost' | 'max_duration'

export interface MicOpenOptions {
  /** RMS (0..1, linear) of each captured block, ~20-40 times per second */
  onLevel(rms: number): void
  /** the capture ended by itself: the device went away, or the maximum duration was reached */
  onEnded(reason: EndedReason): void
  maxSeconds: number
}

export interface MicSession {
  /** Stops capturing, RELEASES the microphone, and returns everything recorded. */
  stop(): Promise<RecordedAudio>
  /** Releases the microphone and throws the audio away. Idempotent. */
  cancel(): void
}

export interface MicCapture {
  /** Asks for the microphone (the browser shows its permission prompt the first time). Rejects with a classifiable error. */
  open(options: MicOpenOptions): Promise<MicSession>
}

/** Raised by us (not by the browser) when the platform cannot capture at all. */
export class MicUnsupported extends Error {
  constructor() {
    super('microphone capture is not supported here')
    this.name = 'MicUnsupported'
  }
}

/** Browser error to the code the UI understands. Names per the MediaDevices.getUserMedia specification. */
export function classifyMicError(e: unknown): VoiceErrorCode {
  if (e instanceof MicUnsupported) return 'unsupported'
  const name = typeof e === 'object' && e !== null && 'name' in e ? String((e as { name: unknown }).name) : ''
  switch (name) {
    case 'NotAllowedError':
    case 'SecurityError':
    case 'PermissionDeniedError':
      return 'permission_denied'
    case 'NotFoundError':
    case 'DevicesNotFoundError':
    case 'OverconstrainedError':
      return 'no_microphone'
    case 'NotReadableError':
    case 'TrackStartError':
    case 'AbortError':
      return 'device_busy'
    default:
      return 'capture_failed'
  }
}

const WORKLET_URL = '/worklets/pcm-capture.js'
const FLUSH_WAIT_MS = 400

export interface BrowserMicEnv {
  mediaDevices?: Pick<MediaDevices, 'getUserMedia'>
  audioContext?: typeof AudioContext
  workletNode?: typeof AudioWorkletNode
  workletUrl?: string
}

export function createBrowserMic(env: BrowserMicEnv = {}): MicCapture {
  return {
    async open({ onLevel, onEnded, maxSeconds }) {
      const mediaDevices = env.mediaDevices ?? (typeof navigator !== 'undefined' ? navigator.mediaDevices : undefined)
      const Ctx = env.audioContext ?? (typeof AudioContext !== 'undefined' ? AudioContext : undefined)
      // `mediaDevices` is undefined outside a secure context (plain http on a non-loopback host): say so instead of failing obscurely
      const WorkletNode = env.workletNode ?? (typeof AudioWorkletNode !== 'undefined' ? AudioWorkletNode : undefined)
      if (!mediaDevices?.getUserMedia || !Ctx || !WorkletNode) throw new MicUnsupported()

      // audio only, never video; the default device. channelCount 1: the voice is mono anyway.
      const stream = await mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true }, video: false })

      let ctx: AudioContext | null = null
      let node: AudioWorkletNode | null = null
      let source: MediaStreamAudioSourceNode | null = null
      let silent: GainNode | null = null
      let released = false
      const chunks: Float32Array[] = []
      let frames = 0
      let flushed: (() => void) | null = null

      /** Every exit path goes through here: tracks stopped, graph torn down, context closed. */
      const release = () => {
        if (released) return
        released = true
        for (const track of stream.getTracks()) {
          track.onended = null
          track.stop()
        }
        if (node) node.port.onmessage = null
        for (const n of [node, source, silent]) {
          try {
            n?.disconnect()
          } catch {
            /* already disconnected */
          }
        }
        void ctx?.close().catch(() => undefined)
      }

      try {
        ctx = new Ctx({ latencyHint: 'interactive' })
        if (ctx.state === 'suspended') await ctx.resume()
        await ctx.audioWorklet.addModule(env.workletUrl ?? WORKLET_URL)
        source = ctx.createMediaStreamSource(stream)
        node = new WorkletNode(ctx, 'pcm-capture', { numberOfInputs: 1, numberOfOutputs: 1, outputChannelCount: [1] })
        silent = ctx.createGain() // the worklet must be pulled by the graph; its output is muted so nothing is ever played back
        silent.gain.value = 0
        source.connect(node)
        node.connect(silent)
        silent.connect(ctx.destination)

        const rate = ctx.sampleRate
        node.port.onmessage = (event: MessageEvent<{ pcm?: Float32Array; flushed?: boolean }>) => {
          if (event.data.flushed) return flushed?.()
          const pcm = event.data.pcm
          if (!pcm || released) return
          chunks.push(pcm)
          frames += pcm.length
          onLevel(rms(pcm))
          if (frames / rate >= maxSeconds) onEnded('max_duration')
        }
        for (const track of stream.getAudioTracks()) track.onended = () => onEnded('device_lost') // unplugged, or access revoked
      } catch (e) {
        release()
        throw e
      }

      const sampleRate = ctx.sampleRate
      return {
        async stop() {
          if (!released && node) {
            // ask the worklet for the block it is still holding, then wait (briefly) for it
            await new Promise<void>((resolve) => {
              const timer = setTimeout(resolve, FLUSH_WAIT_MS)
              flushed = () => {
                clearTimeout(timer)
                resolve()
              }
              node?.port.postMessage('flush')
            })
          }
          release()
          return { samples: concatChunks(chunks), sampleRate }
        },
        cancel() {
          chunks.length = 0
          release()
        },
      }
    },
  }
}
