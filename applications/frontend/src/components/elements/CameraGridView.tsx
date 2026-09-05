import clsx from 'clsx'
import type Hls from 'hls.js'
import { useEffect, useRef } from 'react'
import type { CameraFeed, CameraGridPayload } from '@/api/types'
import { Card } from '@/components/ui/Card'
import { Chip } from '@/components/ui/Chip'
import { Dialog } from '@/components/ui/Dialog'
import { EmptyState } from '@/components/ui/StateBlocks'
import { useUrlParam } from '@/features/filters/useFilters'
import { useLocale } from '@/i18n/LocaleProvider'

/**
 * One card per camera, filtered by a search box over their names, and any one
 * of them zoomed into a dialog by clicking it.
 *
 * `streamUrl` is an HLS playlist, and its absence is the whole of what decides
 * between a player and a placeholder: a feed that is down carries no URL.
 */
export function CameraGridView({ data }: { data: CameraGridPayload }) {
  const { t } = useLocale()
  // Like every other bit of UI state here, the search and the zoomed camera
  // live in the URL: a filtered wall, or one camera full size, is shareable
  // and survives a reload.
  const search = useUrlParam('camera')
  const zoom = useUrlParam('zoom')
  const query = (search.value ?? '').trim().toLowerCase()
  const feeds = query
    ? data.feeds.filter((feed) => `${feed.label} ${feed.zone}`.toLowerCase().includes(query))
    : data.feeds
  const zoomed = data.feeds.find((feed) => feed.id === zoom.value)

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
              <Card className="relative overflow-hidden" interactive>
                <div className="relative aspect-video bg-canvas">
                  <CameraPlayer feed={feed} className="object-cover" />
                  {/* Over the video, so it must not eat the clicks meant for it. */}
                  <span className="pointer-events-none absolute start-2 top-2">
                    <Chip severity={feed.status === 'online' ? 'ok' : 'critical'}>{feed.statusLabel}</Chip>
                  </span>
                </div>
                <div className="px-3 py-2">
                  <div className="truncate text-xs font-medium text-ink">{feed.label}</div>
                  <p className="mt-0.5 line-clamp-2 text-[11px] text-muted">{feed.zone}</p>
                </div>
                {/* Stretched over the whole tile rather than wrapping it: a
                    button may not contain a section, and this way the card
                    keeps one accessible name and one focus stop. Being a
                    button is also what stops the click reaching the element
                    card behind, which would expand the entire grid. */}
                <button
                  type="button"
                  onClick={() => zoom.set(feed.id)}
                  aria-label={`${t.expand}: ${feed.label}`}
                  className="absolute inset-0 cursor-zoom-in rounded-(--radius-card) focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand"
                />
              </Card>
            </li>
          ))}
        </ul>
      )}

      {zoomed ? (
        <Dialog open size="lg" title={zoomed.label} closeLabel={t.close} onClose={() => zoom.set(null)}>
          <div className="aspect-video bg-canvas">
            <CameraPlayer feed={zoomed} className="object-contain" />
          </div>
          <p className="mt-3 text-sm text-muted">{zoomed.zone}</p>
        </Dialog>
      ) : null}
    </div>
  )
}

/**
 * One feed, or its placeholder while it is down.
 *
 * No `controls`: a wall of cameras is watched, not scrubbed, and every tile is
 * pinned to the newest segment anyway. `muted` and `playsInline` are what let a
 * tile start on its own, without a click per camera.
 */
function CameraPlayer({ feed, className }: { feed: CameraFeed; className?: string }) {
  const ref = useRef<HTMLVideoElement>(null)
  const source = feed.streamUrl

  // Attaching a media engine to a DOM node is exactly what an Effect is for.
  useEffect(() => {
    const video = ref.current
    if (!video || !source) return

    // Safari plays HLS itself. Every other browser needs the polyfill, which
    // is imported here rather than at the top of the file so that the tabs
    // with no camera on them never download it.
    if (video.canPlayType('application/vnd.apple.mpegurl')) {
      video.src = source
      return
    }

    let player: Hls | undefined
    let cancelled = false
    void import('hls.js').then(({ default: HlsPlayer }) => {
      if (cancelled) return
      player = new HlsPlayer()
      player.loadSource(source)
      player.attachMedia(video)
    })

    return () => {
      cancelled = true
      player?.destroy()
    }
  }, [source])

  if (!source) {
    return (
      <div className="flex size-full items-center justify-center">
        <span className="font-mono text-2xl font-semibold text-border">{feed.id}</span>
      </div>
    )
  }

  return <video ref={ref} muted autoPlay playsInline className={clsx('size-full', className)} />
}
