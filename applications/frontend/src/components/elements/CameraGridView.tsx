import type { CameraFeed, CameraGridPayload } from '@/api/types'
import { Card } from '@/components/ui/Card'
import { Chip } from '@/components/ui/Chip'
import { EmptyState } from '@/components/ui/StateBlocks'
import { useUrlParam } from '@/features/filters/useFilters'
import { useLocale } from '@/i18n/LocaleProvider'

/**
 * One card per camera, filtered by a search box over their names.
 *
 * The player is the stream server's own page in an iframe: it already sits
 * next to us and carries the playback logic, so the dashboard needs no media
 * library of its own. `streamUrl` is absent while a feed is down, which is the
 * one thing that decides whether a tile plays or shows its placeholder.
 */
export function CameraGridView({ data }: { data: CameraGridPayload }) {
  const { t } = useLocale()
  // Like every other bit of UI state here, the search lives in the URL: a
  // filtered wall of cameras is shareable and survives a reload.
  const search = useUrlParam('camera')
  const query = (search.value ?? '').trim().toLowerCase()
  const feeds = query
    ? data.feeds.filter((feed) => `${feed.label} ${feed.zone}`.toLowerCase().includes(query))
    : data.feeds

  return (
    <div className="flex flex-1 flex-col gap-3">
      <input
        type="search"
        value={search.value ?? ''}
        onChange={(event) => search.set(event.target.value || null)}
        placeholder={t.searchCameras}
        aria-label={t.searchCameras}
        className="w-full max-w-xs rounded-md bg-canvas px-3 py-1.5 text-sm text-ink ring-1 ring-border placeholder:text-muted focus:outline-none focus:ring-2 focus:ring-brand"
      />

      {feeds.length === 0 ? (
        <EmptyState>{t.noCamerasMatch}</EmptyState>
      ) : (
        <ul className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {feeds.map((feed) => (
            <li key={feed.id}>
              <FeedCard feed={feed} />
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function FeedCard({ feed }: { feed: CameraFeed }) {
  return (
    <Card className="overflow-hidden" interactive>
      <div className="relative aspect-video bg-canvas">
        {feed.streamUrl ? (
          <iframe
            src={feed.streamUrl}
            title={feed.label}
            allow="autoplay; fullscreen"
            className="size-full border-0"
          />
        ) : (
          <div className="flex size-full items-center justify-center">
            <span className="font-mono text-2xl font-semibold text-border">{feed.id}</span>
          </div>
        )}
        {/* Over the player, so it must not eat the clicks meant for it. */}
        <span className="pointer-events-none absolute start-2 top-2">
          <Chip severity={feed.status === 'online' ? 'ok' : 'critical'}>{feed.statusLabel}</Chip>
        </span>
      </div>
      <div className="px-3 py-2">
        <div className="truncate text-xs font-medium text-ink">{feed.label}</div>
        <p className="mt-0.5 line-clamp-2 text-[11px] text-muted">{feed.zone}</p>
      </div>
    </Card>
  )
}
