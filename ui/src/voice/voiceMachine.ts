/**
 * The state of ONE voice input at a time, as a pure reducer.
 *
 * Every event carries the session it belongs to. A new session starts only from a resting phase, and a cancel moves the state to a NEW
 * session number, so anything still in flight from the old one (a late permission grant, a late transcription, a late error) names a
 * session that is no longer current and is dropped here, in one place, instead of being checked ad hoc at every await.
 */

export type VoicePhase = 'idle' | 'permission_requested' | 'listening' | 'transcribing' | 'completed' | 'cancelled' | 'error'

export type VoiceErrorCode =
  // the microphone
  | 'permission_denied'
  | 'no_microphone'
  | 'device_busy'
  | 'device_lost'
  | 'unsupported'
  | 'capture_failed'
  // the audio
  | 'too_short'
  | 'no_speech'
  | 'invalid_audio'
  // the Core and its speech engine
  | 'core_offline'
  | 'timeout'
  | 'origin_not_allowed'
  | 'model_missing'
  | 'stt_unavailable'
  | 'stt_disabled'
  | 'stt_busy'
  | 'stt_timeout'
  | 'stt_failed'
  | 'unknown'

export type CancelReason = 'user' | 'focus_lost' | 'navigation' | 'disabled'

export interface VoiceMachineState {
  phase: VoicePhase
  session: number
  error: VoiceErrorCode | null
  /** The recognised text. Kept in memory for the current session only; the product HUD does not show it, development builds do. */
  transcript: string | null
  cancelledBecause: CancelReason | null
}

export type VoiceEvent =
  | { type: 'start'; session: number }
  | { type: 'permission_granted'; session: number }
  | { type: 'stop'; session: number }
  | { type: 'transcribed'; session: number; text: string }
  | { type: 'failed'; session: number; error: VoiceErrorCode }
  | { type: 'cancel'; session: number; reason: CancelReason }
  | { type: 'reset'; session: number }

export const INITIAL_VOICE_STATE: VoiceMachineState = { phase: 'idle', session: 0, error: null, transcript: null, cancelledBecause: null }

export const isBusyPhase = (p: VoicePhase) => p === 'permission_requested' || p === 'listening' || p === 'transcribing'
const isResting = (p: VoicePhase) => !isBusyPhase(p)

export function voiceReducer(s: VoiceMachineState, e: VoiceEvent): VoiceMachineState {
  switch (e.type) {
    case 'start':
      // one capture at a time: a start while anything is in progress changes nothing
      return isResting(s.phase) ? { phase: 'permission_requested', session: e.session, error: null, transcript: null, cancelledBecause: null } : s
    case 'permission_granted':
      return e.session === s.session && s.phase === 'permission_requested' ? { ...s, phase: 'listening' } : s
    case 'stop':
      return e.session === s.session && s.phase === 'listening' ? { ...s, phase: 'transcribing' } : s
    case 'transcribed':
      return e.session === s.session && s.phase === 'transcribing' ? { ...s, phase: 'completed', transcript: e.text } : s
    case 'failed':
      return e.session === s.session && isBusyPhase(s.phase) ? { ...s, phase: 'error', error: e.error, transcript: null } : s
    case 'cancel':
      // moves to the NEW session number the caller reserved, which is what makes every late result of the old one stale
      return isBusyPhase(s.phase) ? { phase: 'cancelled', session: e.session, error: null, transcript: null, cancelledBecause: e.reason } : s
    case 'reset':
      return e.session === s.session && isResting(s.phase) && s.phase !== 'idle' ? { ...INITIAL_VOICE_STATE, session: s.session } : s
  }
}
