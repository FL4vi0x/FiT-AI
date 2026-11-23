/** pt-BR number formatting. `null` is a missing reading and is shown as an em dash, never as zero. */
const formatters = new Map<number, Intl.NumberFormat>()

export function fmtNumber(value: number | null | undefined, decimals = 0, fallback = '—'): string {
  if (value === null || value === undefined || Number.isNaN(value)) return fallback
  let f = formatters.get(decimals)
  if (!f) {
    f = new Intl.NumberFormat('pt-BR', { minimumFractionDigits: decimals, maximumFractionDigits: decimals })
    formatters.set(decimals, f)
  }
  return f.format(value)
}

export function fmtClock(ms: number): string {
  const d = new Date(ms)
  const p = (n: number) => String(n).padStart(2, '0')
  return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
}

/** The Core treats a reading older than this as stale (max_age_s = 10 in the assistant settings). */
export const STALE_AFTER_S = 10

export function parseTimestamp(iso: string, fallbackMs: number): number {
  const t = Date.parse(iso)
  return Number.isNaN(t) ? fallbackMs : t
}

export function ageSeconds(fromMs: number, nowMs: number): number {
  return Math.max(0, Math.round((nowMs - fromMs) / 1000))
}

export function fmtAge(seconds: number): string {
  if (seconds < 2) return 'agora'
  if (seconds < 60) return `há ${seconds} s`
  const m = Math.floor(seconds / 60)
  const s = seconds % 60
  return s === 0 ? `há ${m} min` : `há ${m} min ${s} s`
}

export function fmtLatency(ms: number): string {
  return ms < 1000 ? `${Math.round(ms)} ms` : `${(ms / 1000).toFixed(1).replace('.', ',')} s`
}
