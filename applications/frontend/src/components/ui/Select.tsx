import { useId } from 'react'
import type { FilterOption } from '@/api/types'

/** A labelled native select: keyboard and screen-reader behaviour for free. */
export function Select({
  label,
  value,
  options,
  onChange,
}: {
  label: string
  value: string
  options: FilterOption[]
  onChange: (value: string) => void
}) {
  const id = useId()
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={id} className="text-[11px] font-medium tracking-wide text-muted uppercase">
        {label}
      </label>
      <select
        id={id}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="min-w-40 rounded-lg bg-surface px-3 py-2 text-sm text-ink ring-1 ring-border focus:ring-2 focus:ring-brand focus:outline-none"
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </div>
  )
}
