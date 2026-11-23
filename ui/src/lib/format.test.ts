import { describe, expect, it } from 'vitest'
import { ageSeconds, fmtAge, fmtClock, fmtLatency, fmtNumber, parseTimestamp } from './format'
import { errorText, ORIGIN_META, toolMeta } from './labels'
import { CORE_POS, leaderPoints, PANELS, panelLeader, STAGE, toPath, zoneAnchor } from './vehicleZones'

describe('format', () => {
  it('formats numbers pt-BR and shows a missing value as an em dash, never as zero', () => {
    expect(fmtNumber(820)).toBe('820')
    expect(fmtNumber(1234.5, 1)).toBe('1.234,5')
    expect(fmtNumber(0)).toBe('0')
    expect(fmtNumber(null)).toBe('—')
    expect(fmtNumber(undefined)).toBe('—')
    expect(fmtNumber(Number.NaN)).toBe('—')
  })

  it('formats ages and latencies', () => {
    expect(fmtAge(0)).toBe('agora')
    expect(fmtAge(1)).toBe('agora')
    expect(fmtAge(7)).toBe('há 7 s')
    expect(fmtAge(60)).toBe('há 1 min')
    expect(fmtAge(75)).toBe('há 1 min 15 s')
    expect(fmtLatency(38)).toBe('38 ms')
    expect(fmtLatency(4620)).toBe('4,6 s')
  })

  it('computes ages from timestamps, falling back when a timestamp is unreadable', () => {
    const t = Date.parse('2026-11-21T12:00:00Z')
    expect(ageSeconds(t, t + 15_400)).toBe(15)
    expect(ageSeconds(t, t - 5000)).toBe(0)
    expect(parseTimestamp('2026-11-21T12:00:00Z', 1)).toBe(t)
    expect(parseTimestamp('not a date', 42)).toBe(42)
    expect(fmtClock(new Date(2026, 10, 21, 9, 5, 3).getTime())).toBe('09:05:03')
  })
})

describe('labels', () => {
  it('knows every answer origin the Core can send, and fallback is flagged as a warning', () => {
    for (const o of ['llm', 'llm_retry', 'fallback', 'deterministic', 'policy_refusal', 'memory_command'] as const) {
      expect(ORIGIN_META[o].label).toBeTruthy()
      expect(ORIGIN_META[o].hint.length).toBeGreaterThan(10)
    }
    expect(ORIGIN_META.fallback.tone).toBe('warn')
  })

  it('names the Core tools and survives an unknown one', () => {
    expect(toolMeta('get_vehicle_telemetry').label).toBe('Telemetria')
    expect(toolMeta('get_vehicle_status').label).toBe('Status do veículo')
    expect(toolMeta('get_memory_facts').label).toBe('Memória')
    expect(toolMeta('something_new').label).toBe('something_new')
  })

  it('explains backend error codes, falling back to the server text', () => {
    expect(errorText('service_busy')).toContain('ocupado')
    expect(errorText('model_unavailable')).toContain('Ollama')
    expect(errorText('brand_new_code', 'texto do servidor')).toBe('texto do servidor')
    expect(errorText('brand_new_code')).toContain('brand_new_code')
  })
})

describe('stage geometry', () => {
  it('draws leaders as a straight run and a single 45 degree turn into the anchor', () => {
    const down = leaderPoints({ x: 10, y: 0 }, { x: 50, y: 100 })
    expect(down).toEqual([{ x: 10, y: 0 }, { x: 10, y: 60 }, { x: 50, y: 100 }])
    expect(toPath(down)).toBe('M 10.0 0.0 L 10.0 60.0 L 50.0 100.0')
    const across = leaderPoints({ x: 0, y: 0 }, { x: 100, y: 40 })
    expect(across).toEqual([{ x: 0, y: 0 }, { x: 60, y: 0 }, { x: 100, y: 40 }])
  })

  it('uses a plain straight line when the anchor is level with, or straight under, the start', () => {
    expect(leaderPoints({ x: 0, y: 5 }, { x: 80, y: 5 })).toEqual([{ x: 0, y: 5 }, { x: 80, y: 5 }])
    expect(leaderPoints({ x: 7, y: 0 }, { x: 7, y: 90 })).toEqual([{ x: 7, y: 0 }, { x: 7, y: 90 }])
  })

  it('keeps every leader short and clear of the car body: it never has more than two segments', () => {
    for (const id of ['rpm', 'temp', 'speed', 'system'] as const) {
      const pts = panelLeader(id)
      expect(pts.length).toBeLessThanOrEqual(3)
      expect(pts.at(-1)).toEqual(zoneAnchor(PANELS[id].zone))
    }
  })

  it('keeps every panel and anchor inside the stage and never lets two panels overlap', () => {
    const rects = Object.values(PANELS).map((p) => p.rect)
    for (const r of rects) {
      expect(r.x).toBeGreaterThanOrEqual(0)
      expect(r.y).toBeGreaterThanOrEqual(0)
      expect(r.x + r.w).toBeLessThanOrEqual(STAGE.w)
      expect(r.y + r.h).toBeLessThanOrEqual(STAGE.h)
    }
    for (let i = 0; i < rects.length; i++) {
      for (let j = i + 1; j < rects.length; j++) {
        const a = rects[i]!
        const b = rects[j]!
        const overlap = a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h
        expect(overlap).toBe(false)
      }
    }
    for (const id of ['powertrain', 'cooling', 'motion', 'cabin'] as const) {
      const p = zoneAnchor(id)
      expect(p.x).toBeGreaterThan(0)
      expect(p.x).toBeLessThan(STAGE.w)
      expect(p.y).toBeGreaterThan(0)
      expect(p.y).toBeLessThan(STAGE.h)
    }
    expect(panelLeader('rpm').at(-1)).toEqual(zoneAnchor('powertrain'))
    const core = CORE_POS
    expect(core.x).toBeGreaterThan(0)
    expect(core.y).toBeLessThan(STAGE.h)
  })
})
