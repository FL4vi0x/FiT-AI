// Contracts of the Fit AI Core, mirrored from the backend (fit_ai/api/routes.py, conversation/models.py).
// Nothing here is invented by the UI: if the backend changes, these types change with it.

export interface HealthResponse {
  status: string
  service: string
  version: string
}

export interface TelemetryResponse {
  rpm: number | null
  speed_kmh: number | null
  coolant_temp_c: number | null
  missing: string[]
  source: string
  simulated: boolean | null
  timestamp: string // ISO 8601, timezone-aware
}

export interface StatusResponse {
  available: boolean
  /** 'connected' | 'vehicle_link_down' | an error code such as 'octave_unavailable' / 'octave_timeout' */
  state: string
  source: string
  simulated: boolean | null
  protocol_version: number | null
  octave_version: string | null
  detail: string | null
}

/** Availability of the local language-model server, as the Core reports it (GET /api/v1/llm/status). `unverified`: the check could
 *  not be completed; it says nothing about whether the server is up. */
export type LlmState = 'available' | 'model_not_installed' | 'unavailable' | 'unverified' | 'not_configured'

export interface LlmStatusResponse {
  state: LlmState
  model: string | null
  checked_at: string // ISO 8601
}

export type AnswerOrigin = 'llm' | 'llm_retry' | 'fallback' | 'deterministic' | 'policy_refusal' | 'memory_command'
export type Availability = 'not_requested' | 'ok' | 'partial' | 'stale' | 'unavailable'
export type ModelStatus = 'ok' | 'unavailable' | 'timeout' | 'not_found' | 'error' | 'not_used'

export interface ChatRequest {
  message: string
  conversation_id?: string | null
}

export interface ChatResponse {
  conversation_id: string
  request_id: string
  answer: string
  model: string | null
  answer_origin: AnswerOrigin
  used_tools: string[]
  fallback_used: boolean
  data_source: string | null
  simulated: boolean | null
  availability: Availability
  model_status: ModelStatus
  memory_saved: boolean
  history_saved: boolean
  replayed: boolean
  latency_ms: number
}

/** Error body of every API failure: `{error: {code, message}, request_id?}`. */
export interface ApiErrorBody {
  error: { code: string; message: string }
  request_id?: string | null
}

export const TOOL_TELEMETRY = 'get_vehicle_telemetry'
export const TOOL_STATUS = 'get_vehicle_status'
export const TOOL_MEMORY = 'get_memory_facts'

/** The backend refuses messages above this by default (FIT_AI_CHAT_MAX_MESSAGE_CHARS, hard cap 4000). */
export const MAX_MESSAGE_CHARS = 1000
