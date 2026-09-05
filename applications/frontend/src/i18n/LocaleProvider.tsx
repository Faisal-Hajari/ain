import { createContext, use, useEffect, type ReactNode } from 'react'
import type { Locale } from '@/api/types'
import { dictionary, type Dictionary } from './dictionary'

interface LocaleContextValue {
  locale: Locale
  dir: 'ltr' | 'rtl'
  t: Dictionary
}

const LocaleContext = createContext<LocaleContextValue | null>(null)

/** Locale changes once in a while, so Context is the right home for it. */
export function LocaleProvider({ locale, children }: { locale: Locale; children: ReactNode }) {
  const dir = locale === 'ar' ? 'rtl' : 'ltr'

  // <html lang/dir> is outside React; keeping it in sync is what Effects are for.
  useEffect(() => {
    const root = document.documentElement
    root.lang = locale
    root.dir = dir
  }, [locale, dir])

  return <LocaleContext value={{ locale, dir, t: dictionary[locale] }}>{children}</LocaleContext>
}

export function useLocale(): LocaleContextValue {
  const value = use(LocaleContext)
  if (!value) throw new Error('useLocale must be used inside <LocaleProvider>')
  return value
}
