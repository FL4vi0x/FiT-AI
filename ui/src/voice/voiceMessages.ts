import type { VoiceState } from '../api/types'
import type { CancelReason, VoiceErrorCode, VoicePhase } from './voiceMachine'

/** Short status line shown beside the core, per phase. The HUD stays voice-first: a few words, never a chat. */
export const PHASE_LABEL: Record<VoicePhase, string> = {
  idle: 'Segure para falar',
  permission_requested: 'Aguardando permissão do microfone',
  listening: 'Ouvindo',
  transcribing: 'Reconhecendo',
  completed: 'Entendi',
  cancelled: 'Captura cancelada',
  error: 'Não foi possível ouvir',
}

/** What went wrong and what to do about it, in words a driver understands. */
export const ERROR_TEXT: Record<VoiceErrorCode, string> = {
  permission_denied: 'Permissão do microfone negada. Libere o microfone para este site nas configurações do navegador.',
  no_microphone: 'Nenhum microfone encontrado. Conecte um microfone e tente de novo.',
  device_busy: 'O microfone está em uso por outro aplicativo. Feche-o e tente de novo.',
  device_lost: 'O microfone foi desconectado durante a captura.',
  unsupported: 'Este navegador ou endereço não permite usar o microfone. Abra pelo endereço http://127.0.0.1 ou http://localhost.',
  capture_failed: 'Não foi possível capturar o áudio do microfone.',
  too_short: 'Áudio muito curto. Segure o botão enquanto fala.',
  no_speech: 'Não ouvi nada. Fale mais perto do microfone.',
  invalid_audio: 'O áudio capturado não pôde ser processado.',
  core_offline: 'O Fit AI Core está desconectado. O reconhecimento de voz precisa dele.',
  timeout: 'O reconhecimento demorou demais e foi abandonado.',
  origin_not_allowed: 'O Core recusou esta origem. Inicie o sistema com ui/scripts/start-stack.ps1 (FIT_AI_CHAT_ALLOWED_ORIGINS).',
  model_missing: 'O modelo de reconhecimento de voz não está instalado. Veja docs/poc-09-01-local-stt.md.',
  stt_unavailable: 'O reconhecimento de voz não está instalado neste computador. Veja docs/poc-09-01-local-stt.md.',
  stt_disabled: 'O reconhecimento de voz está desligado nesta instalação.',
  stt_busy: 'Ainda estou reconhecendo a fala anterior. Tente de novo em instantes.',
  stt_timeout: 'O reconhecimento demorou demais e foi abandonado.',
  stt_failed: 'O reconhecimento de voz falhou.',
  unknown: 'Algo deu errado no reconhecimento de voz.',
}

export const CANCEL_TEXT: Record<CancelReason, string> = {
  user: 'Captura cancelada.',
  focus_lost: 'Captura cancelada: a janela perdeu o foco.',
  navigation: 'Captura cancelada: você saiu da tela.',
  disabled: 'Captura cancelada.',
}

/** Why the control cannot be used right now, from the Core's report; null when it can. */
export function unavailableText(state: VoiceState | 'checking' | 'unknown'): string | null {
  switch (state) {
    case 'model_missing':
      return ERROR_TEXT.model_missing
    case 'engine_missing':
    case 'unavailable':
      return ERROR_TEXT.stt_unavailable
    case 'disabled':
      return ERROR_TEXT.stt_disabled
    default:
      return null // available, still checking, or the Core could not be asked: let the user try, the real attempt reports the truth
  }
}
