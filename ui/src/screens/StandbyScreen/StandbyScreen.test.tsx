import { act, cleanup, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import Root, { routeFromHash } from '../../Root'
import { ENTERING_END, SETTLING_END } from '../../motion/timings'
import StandbyScreen from './StandbyScreen'

function mockMatchMedia(reduced: boolean) {
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: reduced && query.includes('prefers-reduced-motion'),
    media: query,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
    onchange: null,
  })) as unknown as typeof window.matchMedia
}

describe('StandbyScreen', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    mockMatchMedia(false)
  })
  afterEach(() => {
    cleanup()
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it('renders without a backend: no fetch, no XHR', () => {
    const fetchSpy = vi.fn()
    vi.stubGlobal('fetch', fetchSpy)
    render(<StandbyScreen />)
    expect(fetchSpy).not.toHaveBeenCalled()
  })

  it('exposes one landmark and one accessible logo, with decorative layers hidden', () => {
    const { container } = render(<StandbyScreen />)
    expect(screen.getByRole('main')).toBeInTheDocument()
    expect(screen.getByRole('img', { name: 'Fit AI' })).toBeInTheDocument()
    for (const id of ['standby-arcs', 'standby-light', 'standby-reflection']) {
      expect(screen.getByTestId(id)).toHaveAttribute('aria-hidden', 'true')
    }
    expect(container.querySelectorAll('[role="img"]')).toHaveLength(1)
  })

  it('shows nothing but the identity: no controls, text, navigation, chat or telemetry', () => {
    const { container } = render(<StandbyScreen />)
    expect(container.querySelectorAll('button, input, textarea, select, a, nav, header, footer, canvas, video, audio')).toHaveLength(0)
    expect(container.textContent?.trim()).toBe('')
    expect(screen.queryByText(/rpm|km\/h|chat|ollama|octave|telemetria/i)).toBeNull()
  })

  it('goes entering -> settling -> idle on the timeline and leaves no timers behind', () => {
    const { unmount } = render(<StandbyScreen />)
    const phase = () => screen.getByTestId('standby-screen').getAttribute('data-phase')
    expect(phase()).toBe('entering')
    act(() => void vi.advanceTimersByTime(ENTERING_END - 1))
    expect(phase()).toBe('entering')
    act(() => void vi.advanceTimersByTime(1))
    expect(phase()).toBe('settling')
    act(() => void vi.advanceTimersByTime(SETTLING_END - ENTERING_END))
    expect(phase()).toBe('idle')
    unmount()
    expect(vi.getTimerCount()).toBe(0)
  })

  it('clears its phase timers when unmounted early', () => {
    const { unmount } = render(<StandbyScreen />)
    unmount()
    expect(vi.getTimerCount()).toBe(0)
  })

  it('reduced motion: idle at once, no sequence', () => {
    mockMatchMedia(true)
    render(<StandbyScreen />)
    const el = screen.getByTestId('standby-screen')
    expect(el).toHaveAttribute('data-phase', 'idle')
    expect(el).toHaveAttribute('data-motion', 'reduced')
    expect(vi.getTimerCount()).toBe(0)
  })
})

describe('Root routing', () => {
  beforeEach(() => mockMatchMedia(false))
  afterEach(() => {
    cleanup()
    window.location.hash = ''
  })

  it('maps only #/hud to the HUD', () => {
    expect(routeFromHash('')).toBe('standby')
    expect(routeFromHash('#/')).toBe('standby')
    expect(routeFromHash('#/hud')).toBe('hud')
  })

  it('opens the Standby by default', () => {
    window.location.hash = ''
    render(<Root />)
    expect(screen.getByTestId('standby-screen')).toBeInTheDocument()
  })
})
