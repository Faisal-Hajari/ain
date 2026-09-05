import type { StatGroupPayload } from '@/api/types'
import { Stat } from '@/components/ui/Stat'
import type { ElementSize } from './ChartFrame'
import { TrendChart } from './TrendChart'

/** Several related numbers on one card - e.g. occupancy total/indoor/outdoor. */
export function StatGroupView({ data, size }: { data: StatGroupPayload; size?: ElementSize }) {
  return (
    <>
      <div className="flex flex-wrap items-start gap-x-8 gap-y-4">
        {data.stats.map((stat, index) => (
          <Stat key={stat.id} stat={stat} size={index === 0 ? 'lg' : 'md'} />
        ))}
      </div>
      {data.trend ? <TrendChart trend={data.trend} size={size} /> : null}
    </>
  )
}
