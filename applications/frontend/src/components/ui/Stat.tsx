import clsx from 'clsx'
import type { Stat as StatValue } from '@/api/types'
import { TrendPill } from './TrendPill'
import { severityText } from './severity'

/** One headline number. Shared by the single-value kpi card and stat groups. */
export function Stat({ stat, size = 'lg' }: { stat: StatValue; size?: 'lg' | 'md' }) {
  return (
    <div className="min-w-0">
      {stat.label ? <div className="text-[11px] tracking-wide text-muted uppercase">{stat.label}</div> : null}
      <div className="mt-1 flex flex-wrap items-baseline gap-2">
        <span
          className={clsx(
            'leading-none font-semibold tabular-nums',
            size === 'lg' ? 'text-3xl' : 'text-2xl',
            severityText[stat.severity ?? 'ok'],
          )}
        >
          {stat.value}
        </span>
        {stat.unit ? <span className="text-sm text-muted">{stat.unit}</span> : null}
        {stat.delta ? <TrendPill delta={stat.delta} /> : null}
      </div>
    </div>
  )
}
