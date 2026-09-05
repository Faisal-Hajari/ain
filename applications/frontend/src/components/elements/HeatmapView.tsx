import type { HeatmapPayload } from '@/api/types'

/** CSS grid beats a chart library for a fixed-size matrix of cells. */
export function HeatmapView({ data }: { data: HeatmapPayload }) {
  // Scale to the cells the labels address, not to everything the payload
  // carries: a matrix wider than xLabels would otherwise inflate max and wash
  // out every cell that is actually drawn.
  const values = data.yLabels
    .flatMap((_, y) => data.xLabels.map((__, x) => data.cells[y]?.[x] ?? null))
    .filter((value): value is number => value !== null)
  // Floor at 1: an all-zero matrix would otherwise divide by zero, and NaN
  // opacity is dropped by the browser - painting "no incidents" at full
  // strength, which is exactly backwards.
  const max = Math.max(1, ...values)

  return (
    <div className="flex-1 overflow-x-auto">
      <div className="min-w-[34rem]">
        <div
          className="grid gap-1"
          style={{ gridTemplateColumns: `4rem repeat(${data.xLabels.length}, minmax(0, 1fr))` }}
        >
          <div />
          {data.xLabels.map((label) => (
            <div key={label} className="text-center text-[10px] text-muted">
              {label}
            </div>
          ))}
          {data.yLabels.map((rowLabel, y) => (
            <div key={`row-${y}`} className="contents">
              <div className="pe-2 text-end text-[11px] text-muted">{rowLabel}</div>
              {data.xLabels.map((colLabel, x) => {
                const value = data.cells[y]?.[x] ?? null
                return (
                  <div
                    key={`cell-${y}-${x}`}
                    title={`${rowLabel} ${colLabel}: ${value ?? '-'} ${data.unit ?? ''}`}
                    className="h-7 rounded-[4px]"
                    style={{
                      background:
                        value === null ? 'var(--color-border)' : 'var(--color-chart-0)',
                      opacity: value === null ? 0.3 : 0.15 + (value / max) * 0.85,
                    }}
                  />
                )
              })}
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
