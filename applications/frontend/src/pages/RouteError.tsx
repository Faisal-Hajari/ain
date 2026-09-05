import { useRouteError } from 'react-router'
import { useLocaleParam } from '@/features/filters/useFilters'
import { dictionary } from '@/i18n/dictionary'

/** Last resort: a throw that escaped every card-level boundary. */
export function RouteError() {
  const error = useRouteError()
  const { locale } = useLocaleParam()
  const t = dictionary[locale]

  console.error('Unhandled render error', error)

  return (
    <div className="flex min-h-full flex-col items-center justify-center gap-3 p-6 text-center text-sm">
      <p className="text-critical">{t.appCrashed}</p>
      <a href="/" className="rounded-md px-3 py-1.5 text-brand ring-1 ring-border">
        {t.backToStart}
      </a>
    </div>
  )
}
