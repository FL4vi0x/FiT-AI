import type { AnswerOrigin, Availability, ModelStatus } from '../api/types'
import { TOOL_MEMORY, TOOL_STATUS, TOOL_TELEMETRY } from '../api/types'

export type Tone = 'neutral' | 'accent' | 'ok' | 'warn' | 'error' | 'dim'

/** How the answer was produced. Mirrors the Core's `answer_origin`; the hints say what each origin guarantees. */
export const ORIGIN_META: Record<AnswerOrigin, { label: string; tone: Tone; hint: string }> = {
  llm: { label: 'modelo', tone: 'accent', hint: 'Gerada pelo modelo local e aprovada pelo verificador de código.' },
  llm_retry: {
    label: 'modelo (2ª tentativa)',
    tone: 'accent',
    hint: 'A 1ª resposta foi rejeitada pelo verificador; a 2ª foi aprovada.',
  },
  fallback: {
    label: 'fallback',
    tone: 'warn',
    hint: 'Montada por código a partir da leitura verificada: o modelo foi rejeitado duas vezes, falhou ou demorou demais.',
  },
  deterministic: { label: 'determinística', tone: 'warn', hint: 'Montada por código, sem o modelo.' },
  policy_refusal: {
    label: 'recusa',
    tone: 'neutral',
    hint: 'Pedido recusado por política (por exemplo, controlar o veículo), sem chamar o modelo nem o veículo.',
  },
  memory_command: {
    label: 'memória',
    tone: 'accent',
    hint: 'Comando explícito de memória. Não é uma leitura do veículo.',
  },
}

export const AVAILABILITY_META: Record<Availability, { label: string; tone: Tone }> = {
  not_requested: { label: 'sem consulta ao veículo', tone: 'dim' },
  ok: { label: 'dado completo', tone: 'ok' },
  partial: { label: 'dado parcial', tone: 'warn' },
  stale: { label: 'leitura desatualizada', tone: 'warn' },
  unavailable: { label: 'dado indisponível', tone: 'error' },
}

export const TOOL_META: Record<string, { label: string; hint: string }> = {
  [TOOL_TELEMETRY]: { label: 'Telemetria', hint: 'get_vehicle_telemetry · leitura de RPM, velocidade e temperatura' },
  [TOOL_STATUS]: { label: 'Status do veículo', hint: 'get_vehicle_status · estado da ligação com o OCTAVE' },
  [TOOL_MEMORY]: { label: 'Memória', hint: 'get_memory_facts · notas que você pediu para lembrar' },
}

export function toolMeta(name: string): { label: string; hint: string } {
  return TOOL_META[name] ?? { label: name, hint: name }
}

export const MODEL_STATUS_TEXT: Record<ModelStatus, string> = {
  ok: 'Modelo respondeu',
  unavailable: 'Modelo indisponível',
  timeout: 'Modelo excedeu o tempo',
  not_found: 'Modelo não instalado',
  error: 'Erro no modelo',
  not_used: 'Modelo não usado',
}

/** Backend error codes (chat + telemetry) in plain Portuguese. Unknown codes fall back to the server's own message. */
export const ERROR_TEXT: Record<string, string> = {
  invalid_message: 'A mensagem é inválida ou longa demais.',
  invalid_request: 'O pedido não está no formato esperado.',
  conversation_not_found: 'A conversa não existe mais. Comece uma nova.',
  request_in_progress: 'Esse pedido já está em andamento.',
  service_busy: 'O assistente está ocupado com outro pedido. Tente de novo em instantes.',
  request_timeout: 'O pedido demorou demais e foi cancelado.',
  model_timeout: 'O modelo demorou demais para responder.',
  model_unavailable: 'O modelo local está indisponível (Ollama parado?).',
  model_not_found: 'O modelo configurado não está instalado no Ollama.',
  audit_unavailable: 'O registro de auditoria está indisponível, então nada foi executado.',
  storage_unavailable: 'Não foi possível gravar a conversa. Tente de novo.',
  chat_unavailable: 'O chat não está configurado no Core.',
  octave_unavailable: 'O OCTAVE está fora do ar.',
  vehicle_link_down: 'A ligação OCTAVE ↔ veículo caiu.',
  no_data: 'O OCTAVE não tem leitura disponível.',
  octave_timeout: 'O OCTAVE não respondeu a tempo.',
  octave_protocol_incompatible: 'Versão do protocolo do OCTAVE incompatível.',
  octave_error: 'Erro no OCTAVE.',
  invalid_host: 'O Core recusou o cabeçalho Host.',
  origin_not_allowed: 'O Core recusou esta origem. Inicie o Core com FIT_AI_CHAT_ALLOWED_ORIGINS.',
  cross_site_request: 'O Core recusou uma requisição entre sites.',
  payload_too_large: 'A mensagem é grande demais.',
}

export function errorText(code: string, serverMessage?: string): string {
  return ERROR_TEXT[code] ?? serverMessage ?? `Erro do Core (${code}).`
}
