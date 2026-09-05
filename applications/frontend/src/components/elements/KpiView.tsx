import type { KpiPayload } from '@/api/types'
import { Stat } from '@/components/ui/Stat'
import type { ElementSize } from './ChartFrame'
import { TrendChart } from './TrendChart'

export function KpiView({ data, size }: { data: KpiPayload; size?: ElementSize }) {
  return (
    <>
      <Stat
        stat={{
          id: 'value',
          label: '',
          value: data.value,
          unit: data.unit,
          severity: data.severity,
          delta: data.delta,
        }}
      />
      {data.trend ? <TrendChart trend={data.trend} size={size} /> : null}
    </>
  )
}
