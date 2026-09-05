import type { ReactElement } from 'react'
import { ResponsiveContainer } from 'recharts'

/** Cards render at 'card'; the pop-out dialog renders the same element bigger. */
export type ElementSize = 'card' | 'expanded'

/** Every chart gets the same box, so cards line up on the grid. */
export function ChartFrame({ height = 220, children }: { height?: number; children: ReactElement }) {
  // min-height, not height: `flex-1` zeroes a flex child's basis, so a card
  // alone in its grid row would otherwise collapse the chart to nothing.
  return (
    <div className="w-full flex-1" style={{ minHeight: height, height }}>
      <ResponsiveContainer width="100%" height="100%">
        {children}
      </ResponsiveContainer>
    </div>
  )
}

/** Every chart draws both axes: line, ticks and title. */
export const axisProps = {
  stroke: 'var(--color-border)',
  tick: { fill: 'var(--color-muted)', fontSize: 11 },
  tickLine: { stroke: 'var(--color-border)' },
  axisLine: { stroke: 'var(--color-border)' },
} as const

/** The compact version, for the trend chart inside a KPI card. */
export const compactAxisProps = {
  stroke: 'var(--color-border)',
  tick: { fill: 'var(--color-muted)', fontSize: 9 },
  tickLine: { stroke: 'var(--color-border)' },
  axisLine: { stroke: 'var(--color-border)' },
} as const

export const tooltipProps = {
  contentStyle: {
    background: 'var(--color-surface)',
    border: '1px solid var(--color-border)',
    borderRadius: 10,
    fontSize: 12,
    color: 'var(--color-ink)',
  },
  labelStyle: { color: 'var(--color-muted)' },
  cursor: { fill: 'var(--color-border)', fillOpacity: 0.35 },
} as const
