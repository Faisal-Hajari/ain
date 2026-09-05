import type { QueryParams } from '@/api/client'
import { useInstanceLog } from '@/api/queries'
import type { ElementDef } from '@/api/types'
import { Chip } from '@/components/ui/Chip'
import { Dialog } from '@/components/ui/Dialog'
import { Skeleton } from '@/components/ui/Skeleton'
import { ErrorState } from '@/components/ui/StateBlocks'
import { useLocale } from '@/i18n/LocaleProvider'
import { severityLabel } from '@/i18n/dictionary'

/** The catalogue's "on click -> instances + clips" drilldown, for any element. */
export function InstanceLogDialog({
  element,
  filters,
  onClose,
}: {
  element: ElementDef
  filters: QueryParams
  onClose: () => void
}) {
  const { t } = useLocale()
  const query = useInstanceLog(element.id, filters)

  return (
    <Dialog open title={`${element.title} · ${t.instances}`} onClose={onClose} closeLabel={t.close}>
      {query.isPending ? (
        <div className="flex flex-col gap-2">
          {[0, 1, 2, 3].map((row) => (
            <Skeleton key={row} className="h-12 w-full" />
          ))}
        </div>
      ) : query.isError ? (
        <ErrorState message={t.loadFailed} retryLabel={t.retry} onRetry={() => void query.refetch()} />
      ) : query.data.instances.length === 0 ? (
        <p className="py-6 text-center text-sm text-muted">{t.noInstances}</p>
      ) : (
        <>
          <p className="mb-3 text-xs text-muted">
            {query.data.total} {t.instanceCount}
          </p>
          <ul className="flex flex-col gap-2">
            {query.data.instances.map((instance) => (
              <li
                key={instance.id}
                className="flex flex-wrap items-center gap-3 rounded-lg bg-canvas px-3 py-2.5 ring-1 ring-border"
              >
                <span className="font-mono text-sm tabular-nums">{instance.timestamp}</span>
                <Chip>{instance.camera}</Chip>
                {instance.severity ? <Chip severity={instance.severity}>{severityLabel(t, instance.severity)}</Chip> : null}
                {instance.detail ? <span className="min-w-0 flex-1 truncate text-xs text-muted">{instance.detail}</span> : null}
                {instance.clipUrl ? (
                  <a
                    href={instance.clipUrl}
                    className="ms-auto rounded-md px-2 py-1 text-xs font-medium text-brand ring-1 ring-border hover:bg-surface"
                  >
                    {t.watchClip}
                  </a>
                ) : null}
              </li>
            ))}
          </ul>
        </>
      )}
    </Dialog>
  )
}
