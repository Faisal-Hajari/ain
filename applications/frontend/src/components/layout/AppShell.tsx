import type { ReactNode } from 'react'
import type { DashboardConfig, Locale } from '@/api/types'
import { FilterBar } from '@/features/filters/FilterBar'
import { SettingsDialog } from '@/features/settings/SettingsDialog'
import { useLocale } from '@/i18n/LocaleProvider'

/** Chrome only: nav rail, filter bar, and the routed content. */
export function AppShell({
  config,
  filterValues,
  onFilterChange,
  locale,
  onLocaleChange,
  sidebar,
  children,
}: {
  config: DashboardConfig
  filterValues: Record<string, string | undefined>
  onFilterChange: (id: string, value: string) => void
  locale: Locale
  onLocaleChange: (locale: Locale) => void
  sidebar: ReactNode
  children: ReactNode
}) {
  const { t } = useLocale()

  return (
    <div className="flex min-h-full">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:m-2 focus:rounded-md focus:bg-surface focus:px-3 focus:py-2"
      >
        {t.skipToContent}
      </a>

      <aside className="hidden w-60 shrink-0 border-e border-border bg-surface md:block">{sidebar}</aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <FilterBar
          defs={config.filters}
          values={filterValues}
          today={config.today}
          locale={locale}
          onChange={onFilterChange}
        />

        <main id="main" className="flex-1 px-6 py-6">
          {children}
        </main>

        <div className="border-t border-border md:hidden">{sidebar}</div>
      </div>

      <SettingsDialog locale={locale} onLocaleChange={onLocaleChange} />
    </div>
  )
}
