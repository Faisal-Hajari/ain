import type { CameraGridPayload } from '@/api/types'
import { Chip } from '@/components/ui/Chip'

/**
 * Feed tiles. The tile shows the backend's thumbnail when there is one and a
 * placeholder otherwise; `streamUrl` is where a player would attach.
 */
export function CameraGridView({ data }: { data: CameraGridPayload }) {
  return (
    <ul className="grid flex-1 grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
      {data.feeds.map((feed) => (
        <li key={feed.id} className="overflow-hidden rounded-lg ring-1 ring-border">
          <div className="relative aspect-video bg-canvas">
            {feed.thumbnailUrl ? (
              <img src={feed.thumbnailUrl} alt="" className="size-full object-cover" />
            ) : (
              <div className="flex size-full items-center justify-center">
                <span className="font-mono text-2xl font-semibold text-border">{feed.id}</span>
              </div>
            )}
            <span className="absolute start-2 top-2">
              <Chip severity={feed.status === 'online' ? 'ok' : 'critical'}>{feed.statusLabel}</Chip>
            </span>
          </div>
          <div className="px-3 py-2">
            <div className="truncate text-xs font-medium text-ink">{feed.label}</div>
            <p className="mt-0.5 line-clamp-2 text-[11px] text-muted">{feed.zone}</p>
          </div>
        </li>
      ))}
    </ul>
  )
}
