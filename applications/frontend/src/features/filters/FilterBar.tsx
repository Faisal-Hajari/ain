import type { DashboardConfig, FilterDef, Locale } from '@/api/types'
import { DateRangePicker } from '@/components/ui/DateRangePicker'
import { Select } from '@/components/ui/Select'
import { useLocale } from '@/i18n/LocaleProvider'

/** Renders whatever filters the backend declares, in the control it asks for. */
export function FilterBar({
  defs,
  values,
  today,
  locale,
  onChange,
}: {
  defs: FilterDef[]
  values: Record<string, string | undefined>
  today: DashboardConfig['today']
  locale: Locale
  onChange: (id: string, value: string) => void
}) {
  const { t } = useLocale()

  return (
    <div className="flex flex-wrap items-end gap-3 border-b border-border bg-surface px-6 py-3">
      {defs.map((def) => {
        const value = values[def.id] ?? def.defaultValue
        return def.control === 'date-range' ? (
          <DateRangePicker
            key={def.id}
            paramKey={def.id}
            label={def.label}
            value={value}
            options={def.options}
            today={today}
            locale={locale}
            labels={{
              from: t.startingFrom,
              chooseStartDate: t.chooseStartDate,
            }}
          />
        ) : (
          <Select
            key={def.id}
            label={def.label}
            value={value}
            options={def.options}
            onChange={(next) => onChange(def.id, next)}
          />
        )
      })}
    </div>
  )
}
