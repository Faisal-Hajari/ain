import { useCallback } from 'react'
import { useSearchParams } from 'react-router'
import type { QueryParams } from '@/api/client'
import type { FilterDef, Locale } from '@/api/types'

/**
 * Writes several search params in one go.
 *
 * This has to be one call: react-router resolves each `setSearchParams` against
 * the current location rather than queueing them like a state setter, so two
 * calls in the same handler would leave only the last one's change.
 *
 * The returned function is stable across renders at a given URL, which is what
 * keeps effects depending on it from re-subscribing on every render. It does
 * change when the URL changes, and has to: react-router rebuilds
 * `setSearchParams` per location, and holding a stale one would resolve the
 * updater against the previous URL - the very bug the patch argument avoids.
 */
export function useUrlWriter() {
  const [, setSearchParams] = useSearchParams()

  return useCallback(
    (patch: Record<string, string | null>) => {
      setSearchParams(
        (current) => {
          const next = new URLSearchParams(current)
          for (const [key, value] of Object.entries(patch)) {
            if (value === null) next.delete(key)
            else next.set(key, value)
          }
          return next
        },
        { replace: true },
      )
    },
    [setSearchParams],
  )
}

/**
 * Any single piece of UI state, kept in the URL rather than in a component.
 * Which dialog is open, what an in-progress form holds - all of it is
 * shareable, survives a reload, and leaves the app with no local state.
 */
export function useUrlParam(key: string) {
  const [searchParams] = useSearchParams()
  const write = useUrlWriter()
  const set = useCallback((value: string | null) => write({ [key]: value }), [key, write])
  return { value: searchParams.get(key), set }
}

/** The language is its own hook: the layout needs it before the config lands. */
export function useLocaleParam() {
  const [searchParams] = useSearchParams()
  const write = useUrlWriter()
  const locale: Locale = searchParams.get('lang') === 'ar' ? 'ar' : 'en'
  return { locale, setLocale: (next: Locale) => write({ lang: next }) }
}

/**
 * Filters live in the URL, so a filtered dashboard is shareable, survives a
 * reload and needs no store. The backend's filter list decides the keys.
 */
export function useFilters(defs: FilterDef[]) {
  const [searchParams] = useSearchParams()
  const write = useUrlWriter()

  const values: QueryParams = {}
  for (const def of defs) {
    values[def.id] = searchParams.get(def.id) ?? def.defaultValue
  }

  return { values, setFilter: (id: string, value: string) => write({ [id]: value }) }
}
