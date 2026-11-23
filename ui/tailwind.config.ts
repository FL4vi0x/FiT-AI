import type { Config } from 'tailwindcss'

// Orange HoloDrive palette (mandatory colours of the P8 brief). Semantic names; raw hex appears only here and in
// index.css (CSS variables for SVG strokes).
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        base: { DEFAULT: '#0B0B0F', raised: '#11131A', lift: '#171A22' },
        fit: {
          ember: '#FF5A1F',
          orange: '#FF7A00',
          amber: '#FF8F1F',
          gold: '#FFB347',
          sun: '#FFC76A',
        },
        ink: { DEFAULT: '#EDF2F7', soft: '#C8D0D8', dim: '#6B7280' },
        ok: '#22C55E',
        warn: '#F59E0B',
        err: '#EF4444',
      },
      fontFamily: {
        // No web fonts: nothing is fetched from the network (the head unit may be offline).
        display: ['"Segoe UI Variable Display"', '"Segoe UI"', 'system-ui', 'sans-serif'],
        sans: ['"Segoe UI Variable Text"', '"Segoe UI"', 'system-ui', 'sans-serif'],
        // technical identifiers only (error codes), never labels
        mono: ['"Cascadia Mono"', '"Cascadia Code"', 'Consolas', 'ui-monospace', 'monospace'],
      },
    },
  },
  plugins: [],
} satisfies Config
