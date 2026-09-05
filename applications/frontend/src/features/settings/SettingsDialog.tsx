import type { Locale } from '@/api/types'
import { Dialog } from '@/components/ui/Dialog'
import { Select } from '@/components/ui/Select'
import { useUrlParam } from '@/features/filters/useFilters'
import { useLocale } from '@/i18n/LocaleProvider'

const LANGUAGES: { value: Locale; label: string }[] = [
  { value: 'en', label: 'English' },
  { value: 'ar', label: 'العربية' },
]

/** Preferences that are not data filters. Open state lives in the URL. */
export function SettingsDialog({
  locale,
  onLocaleChange,
}: {
  locale: Locale
  onLocaleChange: (locale: Locale) => void
}) {
  const { t } = useLocale()
  const panel = useUrlParam('settings')

  if (panel.value !== 'open') return null

  return (
    <Dialog open title={t.settings} onClose={() => panel.set(null)} closeLabel={t.close}>
      <Select
        label={t.language}
        value={locale}
        options={LANGUAGES}
        onChange={(value) => onLocaleChange(value as Locale)}
      />
    </Dialog>
  )
}
