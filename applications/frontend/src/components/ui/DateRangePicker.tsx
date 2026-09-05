import clsx from 'clsx'
import { useId } from 'react'
import type { FilterOption, Locale } from '@/api/types'
import { useUrlParam, useUrlWriter } from '@/features/filters/useFilters'

/**
 * Presets plus a month calendar. Picking a day sets it as the start date, so
 * the value is either a preset key ("7d") or an ISO date ("2026-08-12").
 * `today` comes from the backend so nothing here reads the browser clock.
 */
export function DateRangePicker({
  paramKey,
  label,
  value,
  options,
  today,
  locale,
  labels,
}: {
  /** The search-param this filter owns, written together with the panel state. */
  paramKey: string
  label: string
  value: string
  options: FilterOption[]
  today: string
  locale: Locale
  labels: { from: string; previousMonth: string; nextMonth: string; chooseStartDate: string }
}) {
  const id = useId()
  const panel = useUrlParam('calendar')
  const month = useUrlParam('calendarMonth')
  const write = useUrlWriter()
  const choose = (next: string) => write({ [paramKey]: next, calendar: null, calendarMonth: null })

  const isDate = /^\d{4}-\d{2}-\d{2}$/.test(value)
  const dayFormat = new Intl.DateTimeFormat(locale, { day: 'numeric', month: 'short', year: 'numeric' })
  const monthFormat = new Intl.DateTimeFormat(locale, { month: 'long', year: 'numeric' })
  const weekdayFormat = new Intl.DateTimeFormat(locale, { weekday: 'narrow' })

  const preset = options.find((option) => option.value === value)
  const trigger = preset ? preset.label : `${labels.from} ${dayFormat.format(new Date(value))}`

  const viewed = month.value ?? (isDate ? value.slice(0, 7) : today.slice(0, 7))
  const firstOfMonth = new Date(`${viewed}-01T00:00:00Z`)
  const daysInMonth = new Date(Date.UTC(firstOfMonth.getUTCFullYear(), firstOfMonth.getUTCMonth() + 1, 0)).getUTCDate()
  const leading = firstOfMonth.getUTCDay()
  const cells = [
    ...Array.from({ length: leading }, () => null),
    ...Array.from({ length: daysInMonth }, (_, index) => index + 1),
  ]

  const isoFor = (day: number) => `${viewed}-${String(day).padStart(2, '0')}`
  const shiftMonth = (delta: number) => {
    const shifted = new Date(Date.UTC(firstOfMonth.getUTCFullYear(), firstOfMonth.getUTCMonth() + delta, 1))
    month.set(shifted.toISOString().slice(0, 7))
  }

  const weekdayNames = Array.from({ length: 7 }, (_, index) =>
    weekdayFormat.format(new Date(Date.UTC(2024, 0, 7 + index))),
  )

  const open = panel.value === 'open'

  return (
    <div className="relative flex flex-col gap-1">
      <span id={id} className="text-[11px] font-medium tracking-wide text-muted uppercase">
        {label}
      </span>
      <button
        type="button"
        aria-labelledby={id}
        aria-expanded={open}
        onClick={() => panel.set(open ? null : 'open')}
        className="min-w-40 rounded-lg bg-surface px-3 py-2 text-start text-sm text-ink ring-1 ring-border focus:ring-2 focus:ring-brand focus:outline-none"
      >
        {trigger}
      </button>

      {open ? (
        <div className="absolute top-full z-20 mt-1 w-72 rounded-(--radius-card) bg-surface p-3 shadow-lg ring-1 ring-border">
          <div className="flex flex-wrap gap-1.5">
            {options.map((option) => (
              <button
                key={option.value}
                type="button"
                onClick={() => choose(option.value)}
                className={clsx(
                  'rounded-full px-3 py-1 text-xs font-medium ring-1',
                  option.value === value ? 'bg-brand/10 text-brand ring-brand/30' : 'text-muted ring-border hover:bg-canvas',
                )}
              >
                {option.label}
              </button>
            ))}
          </div>

          <div className="mt-3 border-t border-border pt-3">
            <p className="mb-2 text-[11px] text-muted">{labels.chooseStartDate}</p>
            <div className="flex items-center justify-between gap-2">
              <button
                type="button"
                aria-label={labels.previousMonth}
                onClick={() => shiftMonth(-1)}
                className="rounded-md px-2 py-1 text-xs text-muted ring-1 ring-border hover:bg-canvas"
              >
                ‹
              </button>
              <span className="text-xs font-medium">{monthFormat.format(firstOfMonth)}</span>
              <button
                type="button"
                aria-label={labels.nextMonth}
                onClick={() => shiftMonth(1)}
                className="rounded-md px-2 py-1 text-xs text-muted ring-1 ring-border hover:bg-canvas"
              >
                ›
              </button>
            </div>

            <div className="mt-2 grid grid-cols-7 gap-1">
              {weekdayNames.map((name, index) => (
                <div key={index} className="text-center text-[10px] text-muted">
                  {name}
                </div>
              ))}
              {cells.map((day, index) =>
                day === null ? (
                  <div key={`pad-${index}`} />
                ) : (
                  <button
                    key={isoFor(day)}
                    type="button"
                    disabled={isoFor(day) > today}
                    onClick={() => choose(isoFor(day))}
                    className={clsx(
                      'rounded-md py-1 text-xs tabular-nums',
                      isoFor(day) === value
                        ? 'bg-brand font-semibold text-white'
                        : 'text-ink hover:bg-canvas disabled:text-border disabled:hover:bg-transparent',
                    )}
                  >
                    {day}
                  </button>
                ),
              )}
            </div>
          </div>
        </div>
      ) : null}
    </div>
  )
}
