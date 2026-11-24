import type { ApiErrorBody, ChatRequest, ChatResponse, HealthResponse, LlmStatusResponse, StatusResponse, TelemetryResponse, TranscribeResponse, VoiceStatusResponse } from './types'

/** The server answered with an error (4xx/5xx). `code` is the stable backend code, never free text from the user. */
export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly requestId: string | null
  readonly retryAfterS: number | null
  constructor(status: number, code: string, message: string, requestId: string | null = null, retryAfterS: number | null = null) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.requestId = requestId
    this.retryAfterS = retryAfterS
  }
}

/** The server did not answer: unreachable (`offline`) or too slow (`timeout`). */
export class NetworkError extends Error {
  readonly kind: 'offline' | 'timeout'
  constructor(kind: 'offline' | 'timeout', message: string) {
    super(message)
    this.name = 'NetworkError'
    this.kind = kind
  }
}

/** The caller cancelled the request (a cancelled voice session): not an error to show, the result is simply discarded. */
export class RequestAborted extends Error {
  constructor() {
    super('Requisição cancelada')
    this.name = 'RequestAborted'
  }
}

export interface FitAiApi {
  health(): Promise<HealthResponse>
  status(): Promise<StatusResponse>
  telemetry(): Promise<TelemetryResponse>
  llmStatus(): Promise<LlmStatusResponse>
  chat(req: ChatRequest): Promise<ChatResponse>
  /** Read-only: can the Core transcribe speech? It never opens a microphone and never loads a model. */
  voiceStatus(): Promise<VoiceStatusResponse>
  /** One utterance as a 16 kHz mono 16-bit PCM WAV. The Core transcribes it in memory and keeps nothing. `signal` cancels it. */
  transcribe(wav: Uint8Array, signal?: AbortSignal): Promise<TranscribeResponse>
}

export interface ApiOptions {
  /** Same-origin by default: the dev/preview server proxies /api and /health to the Core. */
  baseUrl?: string
  fetchImpl?: typeof fetch
  /** GET timeout. The Core answers /status in milliseconds and gives OCTAVE ~2 s on /telemetry. */
  timeoutMs?: number
  /** POST /chat timeout: above the Core's own 180 s request timeout, so the Core's answer wins. */
  chatTimeoutMs?: number
  /** POST /voice/transcribe timeout: above the Core's own 30 s engine timeout, so the Core's answer wins. */
  transcribeTimeoutMs?: number
}

function isErrorBody(x: unknown): x is ApiErrorBody {
  if (typeof x !== 'object' || x === null) return false
  const e = (x as { error?: unknown }).error
  return typeof e === 'object' && e !== null && typeof (e as { code?: unknown }).code === 'string'
}

export function createApi(opts: ApiOptions = {}): FitAiApi {
  const baseUrl = opts.baseUrl ?? ''
  const doFetch = opts.fetchImpl ?? ((input: RequestInfo | URL, init?: RequestInit) => fetch(input, init))
  const timeoutMs = opts.timeoutMs ?? 8_000
  const chatTimeoutMs = opts.chatTimeoutMs ?? 200_000
  const transcribeTimeoutMs = opts.transcribeTimeoutMs ?? 45_000

  async function request<T>(path: string, init: RequestInit, limitMs: number, outer?: AbortSignal): Promise<T> {
    const ctl = new AbortController()
    if (outer?.aborted) throw new RequestAborted()
    const onOuterAbort = () => ctl.abort()
    outer?.addEventListener('abort', onOuterAbort, { once: true })
    let timedOut = false
    const timer = setTimeout(() => {
      timedOut = true
      ctl.abort()
    }, limitMs)
    let res: Response
    try {
      res = await doFetch(baseUrl + path, {
        ...init,
        signal: ctl.signal,
        cache: 'no-store',
        credentials: 'omit',
        referrerPolicy: 'no-referrer',
      })
    } catch {
      if (outer?.aborted) throw new RequestAborted()
      if (timedOut) throw new NetworkError('timeout', `Sem resposta em ${Math.round(limitMs / 1000)} s`)
      throw new NetworkError('offline', 'Fit AI Core inacessível')
    } finally {
      clearTimeout(timer)
      outer?.removeEventListener('abort', onOuterAbort)
    }

    if (outer?.aborted) throw new RequestAborted()
    let body: unknown = null
    try {
      body = await res.json()
    } catch {
      body = null
    }
    if (!res.ok) {
      const retry = Number(res.headers.get('Retry-After'))
      if (isErrorBody(body)) {
        throw new ApiError(res.status, body.error.code, body.error.message, body.request_id ?? null, Number.isFinite(retry) && retry > 0 ? retry : null)
      }
      // FastAPI's own errors ({detail: ...}) or a proxy error page: still a controlled failure, never a crash
      throw new ApiError(res.status, `http_${res.status}`, `O Core respondeu HTTP ${res.status}`)
    }
    if (body === null || typeof body !== 'object') {
      throw new ApiError(res.status, 'invalid_response', 'Resposta do Core fora do formato esperado')
    }
    return body as T
  }

  return {
    health: () => request<HealthResponse>('/health', { method: 'GET' }, timeoutMs),
    status: () => request<StatusResponse>('/api/v1/vehicle/status', { method: 'GET' }, timeoutMs),
    telemetry: () => request<TelemetryResponse>('/api/v1/vehicle/telemetry', { method: 'GET' }, timeoutMs),
    llmStatus: () => request<LlmStatusResponse>('/api/v1/llm/status', { method: 'GET' }, timeoutMs),
    voiceStatus: () => request<VoiceStatusResponse>('/api/v1/voice/status', { method: 'GET' }, timeoutMs),
    transcribe: (wav, signal) =>
      request<TranscribeResponse>(
        '/api/v1/voice/transcribe',
        { method: 'POST', headers: { 'Content-Type': 'audio/wav' }, body: wav as BodyInit },
        transcribeTimeoutMs,
        signal,
      ),
    chat: (req) =>
      request<ChatResponse>(
        '/api/v1/chat',
        { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(req) },
        chatTimeoutMs,
      ),
  }
}
