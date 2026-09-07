import type { QueryParams } from '@/api/client'
import { useInstanceLog } from '@/api/queries'
import type { ElementDef, Instance } from '@/api/types'
import { Chip } from '@/components/ui/Chip'
import { Dialog } from '@/components/ui/Dialog'
import { Skeleton } from '@/components/ui/Skeleton'
import { ErrorState } from '@/components/ui/StateBlocks'
import { useUrlParam } from '@/features/filters/useFilters'
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
  // Which clip is open, in the URL like every other bit of UI state here, so
  // one occurrence's video is a link somebody can send.
  const playing = useUrlParam('clip')

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
              <InstanceRow
                key={instance.id}
                instance={instance}
                open={playing.value === instance.id}
                onToggle={() => playing.set(playing.value === instance.id ? null : instance.id)}
              />
            ))}
          </ul>
        </>
      )}
    </Dialog>
  )
}

/**
 * One occurrence, and its clip when it is open.
 *
 * The clip plays here rather than at the end of a link. Following the link
 * navigated the whole dashboard to a bare mp4, which loses the log the reader
 * was working through and every filter that got them to it.
 */
function InstanceRow({
  instance,
  open,
  onToggle,
}: {
  instance: Instance
  open: boolean
  onToggle: () => void
}) {
  const { t } = useLocale()

  return (
    <li className="rounded-lg bg-canvas ring-1 ring-border">
      <div className="flex flex-wrap items-center gap-3 px-3 py-2.5">
        <span className="font-mono text-sm tabular-nums">{instance.timestamp}</span>
        <Chip>{instance.camera}</Chip>
        {instance.severity ? <Chip severity={instance.severity}>{severityLabel(t, instance.severity)}</Chip> : null}
        {instance.detail ? <span className="min-w-0 flex-1 truncate text-xs text-muted">{instance.detail}</span> : null}
        {instance.clipUrl ? (
          <button
            type="button"
            onClick={onToggle}
            aria-expanded={open}
            className="ms-auto rounded-md px-2 py-1 text-xs font-medium text-brand ring-1 ring-border hover:bg-surface"
          >
            {open ? t.hideClip : t.watchClip}
          </button>
        ) : (
          // Recording is a rolling window, so an occurrence can outlive its
          // video. Saying so beats a button that answers 404 and beats an
          // empty space the reader has to interpret.
          <span className="ms-auto text-xs text-muted">{t.noClip}</span>
        )}
      </div>
      {open && instance.clipUrl ? (
        <div className="border-t border-border px-3 pb-3 pt-2">
          {/* Rendered on demand, so the first play waits on ffmpeg. `controls`
              gives the browser's own buffering spinner, and `preload` starts
              the request as soon as the row opens rather than on play.

              `muted` is not a preference: the pipeline records with `-an`
              and these clips carry no audio track at all. It is also what
              tells the caption rule there is nothing to caption, which is
              the truth - an empty <track> would satisfy the linter by
              telling a screen reader that captions exist. */}
          <video
            key={instance.clipUrl}
            src={instance.clipUrl}
            controls
            autoPlay
            muted
            playsInline
            preload="auto"
            className="max-h-[50vh] w-full rounded-md bg-black"
          />
        </div>
      ) : null}
    </li>
  )
}
