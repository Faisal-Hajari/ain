import { useEffect, useRef } from 'react'
import type { QueryParams } from '@/api/client'
import { useElementData } from '@/api/queries'
import type { ElementDef } from '@/api/types'
import { Card, CardBody, CardFooter, CardHeader } from '@/components/ui/Card'
import { Chip, LiveDot } from '@/components/ui/Chip'
import { CardSkeleton } from '@/components/ui/Skeleton'
import { ErrorState } from '@/components/ui/StateBlocks'
import { ExpandedElementDialog } from '@/features/expand/ExpandedElementDialog'
import { useUrlParam } from '@/features/filters/useFilters'
import { InstanceLogDialog } from '@/features/instances/InstanceLogDialog'
import { useLocale } from '@/i18n/LocaleProvider'
import { kindLabel } from '@/i18n/dictionary'
import { ElementBody } from './ElementBody'

const SPAN_CLASS: Record<number, string> = {
  1: 'md:col-span-1',
  2: 'md:col-span-2',
  3: 'md:col-span-3',
  4: 'md:col-span-2 xl:col-span-4',
}

/**
 * One catalogue element on screen: fetches its payload, hands it to the view
 * its type names, and shows the shared loading / error / footer chrome.
 */
export function ElementCard({ element, filters }: { element: ElementDef; filters: QueryParams }) {
  const { t } = useLocale()
  const openLog = useUrlParam('instances')
  const openExpanded = useUrlParam('expanded')
  const query = useElementData(element, filters)
  const cardRef = useRef<HTMLElement>(null)

  const logOpen = openLog.value === element.id
  const expandedOpen = openExpanded.value === element.id
  const expand = () => openExpanded.set(element.id)

  // Bound on the element rather than in JSX: the card must stay a plain region
  // for assistive tech - the header's expand button is the accessible path -
  // while a click anywhere on it still zooms. A JSX handler here would make the
  // whole card falsely interactive and swallow the chart's own pointer events.
  useEffect(() => {
    const card = cardRef.current
    if (!card) return

    const zoom = (event: MouseEvent) => {
      const target = event.target as HTMLElement | null
      // Let the footer's own controls, links and any open dialog win.
      if (target?.closest('button, a, dialog, select, input, label')) return
      expand()
    }

    card.addEventListener('click', zoom)
    return () => card.removeEventListener('click', zoom)
  })

  return (
    <Card ref={cardRef} className={`${SPAN_CLASS[element.span ?? 1]} cursor-zoom-in`} interactive>
      <CardHeader
        title={element.title}
        description={element.description}
        actions={
          <>
            {element.updates === 'realtime' ? <LiveDot label={t.live} /> : null}
            <Chip severity={element.kind === 'alert' ? 'warn' : undefined}>{kindLabel(t, element.kind)}</Chip>
            <button
              type="button"
              onClick={expand}
              aria-label={`${t.expand}: ${element.title}`}
              className="rounded-md px-1.5 py-0.5 text-xs text-muted ring-1 ring-border hover:bg-canvas"
            >
              ⤢
            </button>
          </>
        }
      />
      <CardBody>
        {query.isPending ? (
          <CardSkeleton label={`${t.loading} ${element.title}`} />
        ) : query.isError ? (
          <ErrorState message={t.loadFailed} retryLabel={t.retry} onRetry={() => void query.refetch()} />
        ) : (
          <ElementBody payload={query.data} />
        )}
      </CardBody>

      {element.cameras?.length || element.drilldown ? (
        <CardFooter>
          {element.cameras?.length ? (
            <span className="flex flex-wrap items-center gap-1">
              <span className="me-0.5">{t.cameras}</span>
              {element.cameras.map((camera) => (
                <Chip key={camera}>{camera}</Chip>
              ))}
            </span>
          ) : null}
          {element.drilldown === 'instances' ? (
            <button
              type="button"
              onClick={() => openLog.set(element.id)}
              className="ms-auto rounded-md px-2 py-1 text-[11px] font-medium text-brand ring-1 ring-border hover:bg-canvas"
            >
              {t.viewInstances}
            </button>
          ) : null}
        </CardFooter>
      ) : null}

      {logOpen ? (
        <InstanceLogDialog element={element} filters={filters} onClose={() => openLog.set(null)} />
      ) : null}
      {expandedOpen ? (
        <ExpandedElementDialog element={element} filters={filters} onClose={() => openExpanded.set(null)} />
      ) : null}
    </Card>
  )
}
