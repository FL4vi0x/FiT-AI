import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { VoiceControl } from '../components/active/VoiceControl'
import { createLevelMeter } from './levels'
import { ensurePointerEvent } from './testkit'
import type { VoiceInput } from './useVoiceInput'
import type { VoicePhase } from './voiceMachine'

ensurePointerEvent()

function fake(over: Partial<VoiceInput> = {}): VoiceInput {
  return {
    phase: 'idle', session: 1, error: null, transcript: null, cancelledBecause: null, availability: 'available', hint: null,
    meter: createLevelMeter(), press: vi.fn(), release: vi.fn(), toggle: vi.fn(), cancel: vi.fn(), ...over,
  }
}
const setup = (over: Partial<VoiceInput> = {}) => {
  const voice = fake(over)
  render(<VoiceControl voice={voice} />)
  return { voice, button: screen.getByTestId('voice-control'), status: screen.getByTestId('voice-status') }
}

describe('VoiceControl gestures', () => {
  it('holding the pointer presses, letting go releases', () => {
    const { voice, button } = setup()
    fireEvent.pointerDown(button, { button: 0, pointerId: 1 })
    expect(voice.press).toHaveBeenCalledTimes(1)
    fireEvent.pointerUp(button, { button: 0, pointerId: 1 })
    expect(voice.release).toHaveBeenCalledTimes(1)
  })

  it('ignores the right and middle buttons', () => {
    const { voice, button } = setup()
    fireEvent.pointerDown(button, { button: 2, pointerId: 1 })
    fireEvent.pointerDown(button, { button: 1, pointerId: 1 })
    expect(voice.press).not.toHaveBeenCalled()
  })

  it.each([[' '], ['Enter']])('holding %j presses on key down and releases on key up, and key repeat does not press again', (key) => {
    const { voice, button } = setup()
    fireEvent.keyDown(button, { key })
    fireEvent.keyDown(button, { key, repeat: true })
    fireEvent.keyDown(button, { key, repeat: true })
    expect(voice.press).toHaveBeenCalledTimes(1)
    fireEvent.keyUp(button, { key })
    expect(voice.release).toHaveBeenCalledTimes(1)
  })

  it('other keys do nothing, and Space/Enter do not also produce a click', () => {
    const { voice, button } = setup()
    fireEvent.keyDown(button, { key: 'a' })
    fireEvent.keyUp(button, { key: 'a' })
    fireEvent.keyDown(button, { key: 'Tab' })
    expect(voice.press).not.toHaveBeenCalled()
    const down = new KeyboardEvent('keydown', { key: ' ', bubbles: true, cancelable: true })
    button.dispatchEvent(down)
    expect(down.defaultPrevented).toBe(true) // no native "click on key up" that would toggle a second time
  })

  it('a click that is not a pointer press (assistive technology, detail 0) toggles', () => {
    const { voice, button } = setup()
    fireEvent.click(button, { detail: 0 })
    expect(voice.toggle).toHaveBeenCalledTimes(1)
  })

  it('the click that follows a mouse press does not toggle again (the press already handled it)', () => {
    const { voice, button } = setup()
    fireEvent.click(button, { detail: 1 })
    expect(voice.toggle).not.toHaveBeenCalled()
  })

  it('a hijacked touch (pointer cancel) cancels', () => {
    const { voice, button } = setup({ phase: 'listening' })
    fireEvent.pointerCancel(button)
    expect(voice.cancel).toHaveBeenCalledWith('user')
  })

  it('moving focus away while listening cancels; while resting it does nothing', () => {
    const a = setup({ phase: 'listening' })
    fireEvent.blur(a.button)
    expect(a.voice.cancel).toHaveBeenCalledWith('focus_lost')
    document.body.innerHTML = ''
    const b = setup({ phase: 'idle' })
    fireEvent.blur(b.button)
    expect(b.voice.cancel).not.toHaveBeenCalled()
  })

  it('a long touch does not open the context menu in the middle of a hold', () => {
    const { button } = setup()
    const e = new MouseEvent('contextmenu', { bubbles: true, cancelable: true })
    button.dispatchEvent(e)
    expect(e.defaultPrevented).toBe(true)
  })
})

describe('VoiceControl when the engine cannot be used', () => {
  it.each([['model_missing'], ['engine_missing'], ['unavailable'], ['disabled']] as const)('%s: the control is disabled, nothing is sent, and the reason is shown', (availability) => {
    const { voice, button, status } = setup({ availability })
    expect(button).toHaveAttribute('aria-disabled', 'true')
    fireEvent.pointerDown(button, { button: 0 })
    fireEvent.keyDown(button, { key: ' ' })
    fireEvent.click(button, { detail: 0 })
    expect(voice.press).not.toHaveBeenCalled()
    expect(voice.toggle).not.toHaveBeenCalled()
    expect(status).toHaveAttribute('data-blocked', 'true')
    expect(screen.getByTestId('voice-detail').textContent?.length).toBeGreaterThan(20)
  })

  it('a missing model points to the install instructions', () => {
    setup({ availability: 'model_missing' })
    expect(screen.getByTestId('voice-detail')).toHaveTextContent('docs/poc-09-01-local-stt.md')
  })

  it.each([['checking'], ['unknown'], ['available']] as const)('%s: usable (the real attempt reports the truth)', (availability) => {
    const { button } = setup({ availability })
    expect(button).not.toHaveAttribute('aria-disabled')
  })
})

describe('VoiceControl says what is really happening', () => {
  it.each<[VoicePhase, string]>([
    ['idle', 'Segure para falar'], ['permission_requested', 'Aguardando permissão do microfone'], ['listening', 'Ouvindo'],
    ['transcribing', 'Reconhecendo'], ['completed', 'Entendi'], ['cancelled', 'Captura cancelada'], ['error', 'Não foi possível ouvir'],
  ])('%s -> "%s"', (phase, text) => {
    const { status } = setup({ phase })
    expect(status).toHaveTextContent(text)
    expect(status).toHaveAttribute('data-phase', phase)
  })

  it('"microphone active" is shown ONLY while listening', () => {
    for (const phase of ['idle', 'permission_requested', 'transcribing', 'completed', 'cancelled', 'error'] as VoicePhase[]) {
      document.body.innerHTML = ''
      const { status } = setup({ phase })
      expect(status).not.toHaveTextContent(/microfone ativo/i)
    }
    document.body.innerHTML = ''
    const { status } = setup({ phase: 'listening' })
    expect(status).toHaveTextContent(/microfone ativo/i)
  })

  it('is a live region, and the button announces its state', () => {
    const { button, status } = setup({ phase: 'listening' })
    expect(status).toHaveAttribute('role', 'status')
    expect(status).toHaveAttribute('aria-live', 'polite')
    expect(button).toHaveAttribute('aria-pressed', 'true')
    expect(button.getAttribute('aria-label')).toMatch(/Ouvindo/)
  })

  it('shows what went wrong in plain words', () => {
    setup({ phase: 'error', error: 'permission_denied' })
    expect(screen.getByTestId('voice-detail')).toHaveTextContent(/Permissão do microfone negada/)
  })

  it('says why a capture was cancelled', () => {
    setup({ phase: 'cancelled', cancelledBecause: 'focus_lost' })
    expect(screen.getByTestId('voice-detail')).toHaveTextContent(/perdeu o foco/)
  })

  it('in development builds the recognised text can be seen for validation; resting shows none', () => {
    expect(import.meta.env.DEV).toBe(true) // vitest runs the development configuration
    setup({ phase: 'completed', transcript: 'qual é a velocidade do carro?' })
    expect(screen.getByTestId('voice-transcript')).toHaveTextContent('qual é a velocidade do carro?')
    document.body.innerHTML = ''
    setup({ phase: 'idle', transcript: null })
    expect(screen.queryByTestId('voice-transcript')).toBeNull()
  })
})
