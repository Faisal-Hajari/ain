import clsx from 'clsx'
import { useId } from 'react'
import type { FilterOption, Locale } from '@/api/types'
import { useUrlParam, useUrlWriter } from '@/features/filters/useFilters'

/**
 * `2026-09-02`, and a real day. The round-trip is the point: V8 happily rolls
 * `2026-02-31` over to March 3 rather than returning an invalid Date, so
 * parsing alone would let a nonsense date through.
 */
function isValidDay(value: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false
  const parsed = new Date(`${value}T00:00:00Z`)
  return !Number.isNaN(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value
}

interface CalendarLabels {
  chooseStartDate: string
}

/**
 * Presets plus a native date input. Picking a day sets it as the start date, so
 * the value is either a preset key ("7d") or an ISO date ("2026-08-12").
 * `today` comes from the backend so nothing here reads the browser clock.
 *
 * This control owns its search param rather than taking an `onChange`, because
 * choosing a day has to write the filter and close the panel in a single URL
 * write. A control that only sets one value takes `onChange` and goes through
 * `useFilters` instead - see `Select`.
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
  labels: CalendarLabels & { from: string }
}) {
  const id = useId()
  const panel = useUrlParam('calendar')
  const write = useUrlWriter()
  const choose = (next: string) => write({ [paramKey]: next, calendar: null })

  const dayFormat = new Intl.DateTimeFormat(locale, { day: 'numeric', month: 'short', year: 'numeric' })

  // `value` comes straight off the URL, which anyone can edit or truncate, and
  // `today` is backend JSON. Intl.format throws RangeError on an invalid Date
  // rather than returning a placeholder, so neither reaches a formatter
  // unchecked. Without a trustworthy today there is no bound on future days, so
  // the date input is withheld rather than left unbounded - the presets still work.
  const isDate = isValidDay(value)
  const hasToday = isValidDay(today)

  const preset = options.find((option) => option.value === value)
  const trigger = preset
    ? preset.label
    : isDate
      ? `${labels.from} ${dayFormat.format(new Date(value))}`
      : (options[0]?.label ?? '')

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

          {hasToday ? (
            <div className="mt-3 border-t border-border pt-3">
              <input
                type="date"
                aria-label={labels.chooseStartDate}
                value={isDate ? value : ''}
                max={today}
                onChange={(event) => {
                  // Empty means the user cleared the field; leave the filter alone.
                  if (event.target.value) choose(event.target.value)
                }}
                className="w-full rounded-lg bg-surface px-3 py-2 text-sm text-ink ring-1 ring-border focus:ring-2 focus:ring-brand focus:outline-none"
              />
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  )
}
