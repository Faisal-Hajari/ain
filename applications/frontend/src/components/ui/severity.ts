import type { Severity } from '@/api/types'

/** One place maps a backend severity to colour, so cards stay consistent. */
export const severityText: Record<Severity, string> = {
  ok: 'text-ok',
  info: 'text-info',
  warn: 'text-warn',
  critical: 'text-critical',
}

export const severityChip: Record<Severity, string> = {
  ok: 'bg-ok/10 text-ok ring-ok/25',
  info: 'bg-info/10 text-info ring-info/25',
  warn: 'bg-warn/10 text-warn ring-warn/25',
  critical: 'bg-critical/10 text-critical ring-critical/25',
}

export const CHART_COLORS = [
  'var(--color-chart-0)',
  'var(--color-chart-1)',
  'var(--color-chart-2)',
  'var(--color-chart-3)',
  'var(--color-chart-4)',
  'var(--color-chart-5)',
]

export const chartColor = (index = 0) => CHART_COLORS[index % CHART_COLORS.length]!
