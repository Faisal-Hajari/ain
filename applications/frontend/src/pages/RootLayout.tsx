import { Outlet } from 'react-router'
import { useDashboardConfig } from '@/api/queries'
import type { DashboardConfig, FilterDef } from '@/api/types'
import type { QueryParams } from '@/api/client'
import { AppShell } from '@/components/layout/AppShell'
import { Sidebar } from '@/components/layout/Sidebar'
import { Skeleton } from '@/components/ui/Skeleton'
import { useFilters, useLocaleParam } from '@/features/filters/useFilters'
import { LocaleProvider } from '@/i18n/LocaleProvider'
import { dictionary } from '@/i18n/dictionary'

const NO_FILTERS: FilterDef[] = []

export interface DashboardContext {
  config: DashboardConfig
  filters: QueryParams
}

/**
 * Fetches the layout once and hands it, plus the active filters, to every
 * routed page through the outlet context.
 */
export function RootLayout() {
  const { locale, setLocale } = useLocaleParam()
  const configQuery = useDashboardConfig(locale)
  const config = configQuery.data
  const { values, setFilter } = useFilters(config?.filters ?? NO_FILTERS)

  // The language reaches the backend with every request, so payload text and
  // formatting are localised server-side too.
  const filters: QueryParams = { ...values, lang: locale }

  if (configQuery.isPending) {
    return (
      <div className="flex min-h-full flex-col gap-4 p-6" role="status" aria-label={dictionary[locale].loading}>
        <Skeleton className="h-10 w-64" />
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
          {[0, 1, 2, 3, 4, 5, 6, 7].map((card) => (
            <Skeleton key={card} className="h-44 w-full" />
          ))}
        </div>
      </div>
    )
  }

  if (configQuery.isError || !config) {
    return (
      <div className="flex min-h-full flex-col items-center justify-center gap-3 p-6 text-sm">
        <p className="text-critical">{dictionary[locale].configFailed}</p>
        <button type="button" onClick={() => void configQuery.refetch()} className="rounded-md px-3 py-1.5 ring-1 ring-border">
          {dictionary[locale].retry}
        </button>
      </div>
    )
  }

  return (
    <LocaleProvider locale={locale}>
      <AppShell
        config={config}
        filterValues={values}
        onFilterChange={setFilter}
        locale={locale}
        onLocaleChange={setLocale}
        sidebar={<Sidebar sections={config.sections} branchLabel={config.branchLabel} />}
      >
        <Outlet context={{ config, filters } satisfies DashboardContext} />
      </AppShell>
    </LocaleProvider>
  )
}
