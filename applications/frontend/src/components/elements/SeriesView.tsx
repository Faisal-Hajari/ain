import {
  Bar,
  BarChart,
  CartesianGrid,
  Label,
  Legend,
  Line,
  LineChart,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { ElementType, SeriesPayload } from '@/api/types'
import { chartColor } from '@/components/ui/severity'
import { ChartFrame, axisProps, tooltipProps, type ElementSize } from './ChartFrame'

/** line, bar, stacked-bar and histogram all read the same payload shape. */
export function SeriesView({
  type,
  data,
  size,
}: {
  type: Extract<ElementType, 'line' | 'bar' | 'stacked-bar' | 'histogram'>
  data: SeriesPayload
  size?: ElementSize
}) {
  const showLegend = data.series.length > 1
  const grid = <CartesianGrid stroke="var(--color-border)" strokeDasharray="3 3" vertical={false} />

  // Both axes are always titled: a chart that does not say what it is counting
  // is a decoration. The backend supplies the wording.
  const axisLabel = { fill: 'var(--color-muted)', fontSize: 11 }
  const xTitle = data.xLabel ? <Label value={data.xLabel} position="insideBottom" offset={-6} style={axisLabel} /> : null
  const yTitle = data.yLabel ? (
    <Label value={data.yLabel} angle={-90} position="insideLeft" style={axisLabel} />
  ) : null
  const margin = { top: 8, right: 8, bottom: 18, left: 4 }
  const height = size === 'expanded' ? 480 : 220

  if (type === 'line') {
    return (
      <ChartFrame height={height}>
        <LineChart data={data.points} margin={margin}>
          {grid}
          <XAxis dataKey="x" {...axisProps}>
            {xTitle}
          </XAxis>
          <YAxis {...axisProps} width={52}>
            {yTitle}
          </YAxis>
          <Tooltip {...tooltipProps} />
          {showLegend ? <Legend wrapperStyle={{ fontSize: 11 }} /> : null}
          {data.series.map((series) => (
            <Line
              key={series.id}
              type="monotone"
              dataKey={series.id}
              name={series.label}
              stroke={chartColor(series.colorIndex)}
              strokeWidth={2}
              dot={false}
            />
          ))}
        </LineChart>
      </ChartFrame>
    )
  }

  const stacked = type === 'stacked-bar'
  return (
    <ChartFrame height={height}>
      <BarChart data={data.points} margin={margin} barCategoryGap={type === 'histogram' ? 2 : '20%'}>
        {grid}
        <XAxis dataKey="x" {...axisProps}>
          {xTitle}
        </XAxis>
        <YAxis {...axisProps} width={52}>
          {yTitle}
        </YAxis>
        <Tooltip {...tooltipProps} />
        {showLegend ? <Legend wrapperStyle={{ fontSize: 11 }} /> : null}
        {data.series.map((series) => (
          <Bar
            key={series.id}
            dataKey={series.id}
            name={series.label}
            stackId={stacked ? 'stack' : undefined}
            fill={chartColor(series.colorIndex)}
            radius={stacked ? 0 : [6, 6, 0, 0]}
          />
        ))}
      </BarChart>
    </ChartFrame>
  )
}
