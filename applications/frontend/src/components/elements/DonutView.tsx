import { Cell, Legend, Pie, PieChart, Tooltip } from 'recharts'
import type { DonutPayload } from '@/api/types'
import { chartColor } from '@/components/ui/severity'
import { ChartFrame, tooltipProps, type ElementSize } from './ChartFrame'

export function DonutView({ data, size }: { data: DonutPayload; size?: ElementSize }) {
  return (
    <div className="relative flex flex-1 flex-col">
      <ChartFrame height={size === 'expanded' ? 480 : 220}>
        <PieChart>
          <Tooltip {...tooltipProps} cursor={false} />
          <Legend wrapperStyle={{ fontSize: 11 }} />
          <Pie data={data.slices} dataKey="value" nameKey="label" innerRadius="58%" outerRadius="82%" paddingAngle={2} stroke="none">
            {data.slices.map((slice) => (
              <Cell key={slice.id} fill={chartColor(slice.colorIndex)} />
            ))}
          </Pie>
        </PieChart>
      </ChartFrame>
      {data.centerValue ? (
        <div className="pointer-events-none absolute inset-x-0 top-[38%] text-center">
          <div className="text-xl font-semibold tabular-nums">{data.centerValue}</div>
          <div className="text-[11px] text-muted">{data.centerLabel}</div>
        </div>
      ) : null}
    </div>
  )
}
