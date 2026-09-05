import type { QueryParams } from '@/api/client'
import type { SectionDef } from '@/api/types'
import { ElementCard } from '@/components/elements/ElementCard'
import { EmptyState } from '@/components/ui/StateBlocks'
import { useLocale } from '@/i18n/LocaleProvider'

/** A section is just its element list on a 4-column card grid. */
export function SectionGrid({ section, filters }: { section: SectionDef; filters: QueryParams }) {
  const { t } = useLocale()

  return (
    <section aria-labelledby={`section-${section.id}`} className="flex flex-col gap-4">
      <header>
        <h2 id={`section-${section.id}`} className="text-xl font-semibold">
          {section.title}
        </h2>
        {section.description ? <p className="mt-1 max-w-3xl text-sm text-muted">{section.description}</p> : null}
      </header>

      {section.elements.length === 0 ? (
        <EmptyState>{t.noElements}</EmptyState>
      ) : (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
          {section.elements.map((element) => (
            <ElementCard key={element.id} element={element} filters={filters} />
          ))}
        </div>
      )}
    </section>
  )
}
