import type { QueryParams } from '@/api/client'
import { useElementData } from '@/api/queries'
import type { ElementDef } from '@/api/types'
import { ElementBody } from '@/components/elements/ElementBody'
import { Chip } from '@/components/ui/Chip'
import { Dialog } from '@/components/ui/Dialog'
import { ErrorBoundary } from '@/components/ui/ErrorBoundary'
import { CardSkeleton } from '@/components/ui/Skeleton'
import { ErrorState } from '@/components/ui/StateBlocks'
import { useLocale } from '@/i18n/LocaleProvider'
import { kindLabel } from '@/i18n/dictionary'

/**
 * The same element, rendered large. It re-uses the card's query, so opening the
 * pop-out is instant and the two views can never show different numbers.
 */
export function ExpandedElementDialog({
  element,
  filters,
  onClose,
}: {
  element: ElementDef
  filters: QueryParams
  onClose: () => void
}) {
  const { t } = useLocale()
  const query = useElementData(element, filters)

  return (
    <Dialog open size="lg" title={element.title} onClose={onClose} closeLabel={t.close}>
      <div className="flex flex-col gap-4">
        <div className="flex flex-wrap items-center gap-2">
          <Chip severity={element.kind === 'alert' ? 'warn' : undefined}>{kindLabel(t, element.kind)}</Chip>
          {element.cameras?.map((camera) => (
            <Chip key={camera}>{`${t.cameras} ${camera}`}</Chip>
          ))}
        </div>
        {element.description ? <p className="text-sm text-muted">{element.description}</p> : null}

        <div className="flex min-h-80 flex-col">
          {query.isPending ? (
            <CardSkeleton label={`${t.loading} ${element.title}`} />
          ) : query.isError ? (
            <ErrorState message={t.loadFailed} retryLabel={t.retry} onRetry={() => void query.refetch()} />
          ) : (
            <ErrorBoundary
              resetKey={query.dataUpdatedAt.toString()}
              fallback={() => <ErrorState message={t.cardCrashed} retryLabel={t.retry} onRetry={() => void query.refetch()} />}
            >
              <ElementBody payload={query.data} size="expanded" />
            </ErrorBoundary>
          )}
        </div>
      </div>
    </Dialog>
  )
}
