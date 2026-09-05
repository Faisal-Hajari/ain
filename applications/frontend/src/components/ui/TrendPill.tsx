import clsx from 'clsx'
import type { Delta } from '@/api/types'
import { severityChip } from './severity'

const ARROW: Record<Delta['direction'], string> = { up: '▲', down: '▼', flat: '■' }

/** The backend decides both the number and whether it is good news. */
export function TrendPill({ delta }: { delta: Delta }) {
  return (
    <span
      className={clsx(
        'inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold ring-1',
        severityChip[delta.sentiment],
      )}
    >
      <span aria-hidden="true">{ARROW[delta.direction]}</span>
      {delta.label}
    </span>
  )
}
