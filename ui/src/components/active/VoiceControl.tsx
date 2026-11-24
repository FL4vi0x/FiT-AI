import type { KeyboardEvent, PointerEvent } from 'react'
import { isBusyPhase } from '../../voice/voiceMachine'
import { CANCEL_TEXT, ERROR_TEXT, PHASE_LABEL, unavailableText } from '../../voice/voiceMessages'
import type { VoiceInput } from '../../voice/useVoiceInput'
import styles from '../../screens/ActiveScreen/ActiveScreen.module.css'

const PRESS_KEYS = new Set([' ', 'Enter'])

/**
 * The push-to-talk control, laid over the AI core (the core IS the control: no extra chrome). Hold it (pointer, touch, Space or Enter)
 * and speak; let go to send. A quick tap starts listening and the next tap stops it, which is the accessible alternative to holding.
 * Escape cancels. Nothing here records anything: it only forwards gestures to `useVoiceInput`.
 *
 * The status beside the core says what is REALLY happening: "Ouvindo" appears only while the microphone is open.
 */
export function VoiceControl({ voice }: { voice: VoiceInput }) {
  const { phase } = voice
  const blocked = unavailableText(voice.availability)
  const busy = isBusyPhase(phase)
  const listening = phase === 'listening'

  const onPointerDown = (e: PointerEvent<HTMLButtonElement>) => {
    if (e.button !== 0 || blocked) return
    e.preventDefault()
    e.currentTarget.setPointerCapture?.(e.pointerId) // keep the release even if the pointer leaves the circle while held
    voice.press()
  }
  const onPointerUp = (e: PointerEvent<HTMLButtonElement>) => {
    if (blocked) return
    e.currentTarget.releasePointerCapture?.(e.pointerId)
    voice.release()
  }
  const onKeyDown = (e: KeyboardEvent<HTMLButtonElement>) => {
    if (!PRESS_KEYS.has(e.key)) return
    e.preventDefault() // no synthetic click: the press/release below is the whole gesture
    if (!e.repeat && !blocked) voice.press()
  }
  const onKeyUp = (e: KeyboardEvent<HTMLButtonElement>) => {
    if (!PRESS_KEYS.has(e.key)) return
    e.preventDefault()
    if (!blocked) voice.release()
  }

  const label = listening
    ? 'Ouvindo. Solte para enviar, ou toque para parar. Escape cancela.'
    : busy
      ? 'Processando. Escape cancela.'
      : 'Falar com o Fit AI. Segure para falar, ou toque para iniciar e parar.'

  const detail =
    blocked ??
    (phase === 'error' && voice.error ? ERROR_TEXT[voice.error] : phase === 'cancelled' && voice.cancelledBecause ? CANCEL_TEXT[voice.cancelledBecause] : null)

  return (
    <>
      <button
        type="button"
        className={styles.voiceControl}
        data-testid="voice-control"
        data-phase={phase}
        aria-label={label}
        aria-pressed={listening}
        aria-disabled={blocked ? true : undefined}
        onPointerDown={onPointerDown}
        onPointerUp={onPointerUp}
        onPointerCancel={() => voice.cancel('user')}
        onKeyDown={onKeyDown}
        onKeyUp={onKeyUp}
        onBlur={() => (phase === 'listening' || phase === 'permission_requested') && voice.cancel('focus_lost')}
        onClick={(e) => {
          if (e.detail === 0 && !blocked) voice.toggle() // a click that is not a pointer press: assistive technology
        }}
        onContextMenu={(e) => e.preventDefault()} // a long touch must not open a menu in the middle of a hold
      />
      <div className={styles.voiceStatus} data-testid="voice-status" data-phase={phase} data-blocked={blocked ? 'true' : undefined} role="status" aria-live="polite">
        <span className={styles.voiceStatusLine}>
          <i className={styles.voiceDot} data-on={listening ? 'true' : undefined} aria-hidden="true" />
          {blocked ? 'Voz indisponível' : PHASE_LABEL[phase]}
        </span>
        {listening && <span className={styles.voiceMic}>Microfone ativo</span>}
        {phase === 'idle' && !blocked && <span className={styles.voiceHint}>ou toque para iniciar e parar</span>}
        {detail && <span className={styles.voiceDetail} data-testid="voice-detail">{detail}</span>}
      </div>
      {import.meta.env.DEV && voice.transcript && (
        // development builds only: the product HUD stays voice-first with no text. Never sent anywhere from here.
        <div className={styles.voiceTranscript} data-testid="voice-transcript">
          <small>DEV · texto reconhecido</small>
          <p>{voice.transcript}</p>
        </div>
      )}
    </>
  )
}
