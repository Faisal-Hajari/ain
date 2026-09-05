import type { GaugePayload } from '@/api/types'
import { severityText } from '@/components/ui/severity'

const SWEEP = Math.PI * 70 // arc length of the r=70 half-circle below

/** Plain SVG half-gauge: no chart library needed for a single arc. */
export function GaugeView({ data }: { data: GaugePayload }) {
  const span = data.max - data.min || 1
  const ratio = Math.min(1, Math.max(0, (data.value - data.min) / span))
  const stroke =
    data.severity === 'critical'
      ? 'var(--color-critical)'
      : data.severity === 'warn'
        ? 'var(--color-warn)'
        : 'var(--color-ok)'

  return (
    <div className="flex flex-1 flex-col items-center justify-center">
      <svg viewBox="0 0 160 92" className="w-full max-w-56" role="img" aria-label={data.valueLabel}>
        <path d="M10 82 A70 70 0 0 1 150 82" fill="none" stroke="var(--color-border)" strokeWidth="14" strokeLinecap="round" />
        <path
          d="M10 82 A70 70 0 0 1 150 82"
          fill="none"
          stroke={stroke}
          strokeWidth="14"
          strokeLinecap="round"
          strokeDasharray={`${ratio * SWEEP} ${SWEEP}`}
        />
      </svg>
      <div className={`-mt-4 text-3xl font-semibold tabular-nums ${severityText[data.severity ?? 'ok']}`}>
        {data.valueLabel}
      </div>
      {data.minLabel && data.maxLabel ? (
        <div className="mt-1 text-xs text-muted">
          {data.minLabel} – {data.maxLabel}
        </div>
      ) : null}
    </div>
  )
}
