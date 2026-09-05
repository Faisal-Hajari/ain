import type { HeatmapPayload } from '@/api/types'

/** CSS grid beats a chart library for a fixed-size matrix of cells. */
export function HeatmapView({ data }: { data: HeatmapPayload }) {
  const values = data.cells.flat().filter((value): value is number => value !== null)
  const max = values.length ? Math.max(...values) : 1

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
            <div key={rowLabel} className="contents">
              <div className="pe-2 text-end text-[11px] text-muted">{rowLabel}</div>
              {data.xLabels.map((colLabel, x) => {
                const value = data.cells[y]?.[x] ?? null
                return (
                  <div
                    key={colLabel}
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
