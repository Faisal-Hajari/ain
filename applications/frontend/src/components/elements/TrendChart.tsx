import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import type { TrendPayload } from '@/api/types'
import { chartColor } from '@/components/ui/severity'
import { compactAxisProps, tooltipProps, type ElementSize } from './ChartFrame'

/**
 * The trend chart inside a KPI card. Small, but still a chart: it carries both
 * axes, and one line per series so a split (indoor / outdoor / total) reads
 * over time as well as it does as a headline number.
 */
export function TrendChart({ trend, size = 'card' }: { trend: TrendPayload; size?: ElementSize }) {
  const expanded = size === 'expanded'
  const showLegend = trend.series.length > 1

  return (
    <div className={expanded ? 'mt-4 h-80 w-full' : 'mt-4 h-28 w-full'}>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={trend.points} margin={{ top: 6, right: 6, bottom: 0, left: -8 }}>
          <CartesianGrid stroke="var(--color-border)" strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey="x" {...compactAxisProps} interval="preserveStartEnd" minTickGap={24} />
          <YAxis {...compactAxisProps} width={30} />
          {expanded ? <Tooltip {...tooltipProps} /> : null}
          {showLegend ? <Legend wrapperStyle={{ fontSize: 11 }} /> : null}
          {trend.series.map((series) => (
            <Line
              key={series.id}
              type="monotone"
              dataKey={series.id}
              name={series.label}
              stroke={chartColor(series.colorIndex)}
              strokeWidth={2}
              dot={false}
              isAnimationActive={false}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}
