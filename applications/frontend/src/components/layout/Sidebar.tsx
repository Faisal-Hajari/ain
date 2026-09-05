import { NavLink, useLocation } from 'react-router'
import type { SectionDef } from '@/api/types'
import { useUrlParam } from '@/features/filters/useFilters'
import { useLocale } from '@/i18n/LocaleProvider'

export function Sidebar({ sections, branchLabel }: { sections: SectionDef[]; branchLabel: string }) {
  const { t } = useLocale()
  const { search } = useLocation()
  const settings = useUrlParam('settings')

  return (
    <nav aria-label={t.sections} className="flex h-full flex-col gap-1 p-3">
      <div className="px-3 pt-1 pb-3">
        <div className="text-lg leading-tight font-semibold">{t.appName}</div>
        <div className="text-[11px] text-muted">{branchLabel}</div>
      </div>

      {sections.map((section) => (
        <NavLink
          key={section.id}
          to={{ pathname: `/s/${section.id}`, search }}
          className={({ isActive }) =>
            `rounded-lg px-3 py-2 text-sm transition ${
              isActive ? 'bg-brand/10 font-medium text-brand' : 'text-muted hover:bg-canvas hover:text-ink'
            }`
          }
        >
          {section.title}
        </NavLink>
      ))}

      <button
        type="button"
        onClick={() => settings.set('open')}
        className="mt-auto rounded-lg px-3 py-2 text-start text-sm text-muted transition hover:bg-canvas hover:text-ink"
      >
        {t.settings}
      </button>
    </nav>
  )
}
