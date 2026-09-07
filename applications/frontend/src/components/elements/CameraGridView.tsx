import clsx from 'clsx'
import type Hls from 'hls.js'
import { useEffect, useRef } from 'react'
import type { CameraFeed, CameraGridPayload } from '@/api/types'
import { CameraOverlay } from '@/components/elements/CameraOverlay'
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
  const boxes = useUrlParam('boxes')
  const zones = useUrlParam('zones')
  const query = (search.value ?? '').trim().toLowerCase()
  const feeds = query
    ? data.feeds.filter((feed) => `${feed.label} ${feed.zone}`.toLowerCase().includes(query))
    : data.feeds
  const zoomed = data.feeds.find((feed) => feed.id === zoom.value)
  const showBoxes = boxes.value === '1'
  const showZones = zones.value === '1'

  return (
    <div className="flex flex-1 flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <input
          type="search"
          value={search.value ?? ''}
          onChange={(event) => search.set(event.target.value || null)}
          placeholder={t.searchCameras}
          aria-label={t.searchCameras}
          className="w-full max-w-xs rounded-md bg-canvas px-3 py-1.5 text-sm text-ink ring-1 ring-border placeholder:text-muted focus:outline-none focus:ring-2 focus:ring-brand"
        />
        {/* The boxes are drawn on a canvas over the video rather than burnt
            into it, which is what lets one encoded stream serve a viewer who
            wants them and a viewer who does not. */}
        <OverlayToggle label={t.detections} on={showBoxes} onChange={(next) => boxes.set(next ? '1' : null)} />
        <OverlayToggle label={t.zones} on={showZones} onChange={(next) => zones.set(next ? '1' : null)} />
      </div>

      {feeds.length === 0 ? (
        <EmptyState>{t.noCamerasMatch}</EmptyState>
      ) : (
        <ul className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {feeds.map((feed) => (
            <li key={feed.id}>
              <Card className="relative overflow-hidden" interactive>
                <div className="relative aspect-video bg-canvas">
                  {/* Not while the dialog is showing this same camera: two
                      players on one feed is two media engines and two
                      overlay poll loops, for a tile nobody can see. */}
                  {zoom.value === feed.id ? null : (
                    <CameraPlayer feed={feed} fit="cover" showBoxes={showBoxes} showZones={showZones} />
                  )}
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
                  className="absolute inset-0 rounded-(--radius-card) focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand"
                />
              </Card>
            </li>
          ))}
        </ul>
      )}

      {zoomed ? (
        <Dialog open size="lg" title={zoomed.label} closeLabel={t.close} onClose={() => zoom.set(null)}>
          {/* Capped rather than left to the aspect ratio: a 16:9 box this wide
              is taller than the dialog body, which scrolls past 70vh. The cap
              is that 70vh less the padding and the caption under it, so this
              fits at any viewport height rather than at a guessed one.
              object-contain letterboxes whatever the cap takes off. */}
          <div className="relative aspect-video max-h-[calc(70vh_-_7rem)] bg-canvas">
            <CameraPlayer feed={zoomed} fit="contain" showBoxes={showBoxes} showZones={showZones} />
          </div>
          <p className="mt-3 text-sm text-muted">{zoomed.zone}</p>
        </Dialog>
      ) : null}
    </div>
  )
}

/** One on/off control over what is drawn on top of every tile. */
function OverlayToggle({
  label,
  on,
  onChange,
}: {
  label: string
  on: boolean
  onChange: (next: boolean) => void
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      onClick={() => onChange(!on)}
      className={clsx(
        'rounded-md px-3 py-1.5 text-sm ring-1 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-brand',
        on ? 'bg-brand/15 text-ink ring-brand' : 'bg-canvas text-muted ring-border hover:text-ink',
      )}
    >
      {label}
    </button>
  )
}

/**
 * One feed, or its placeholder while it is down.
 *
 * No `controls`, and no picture-in-picture: a wall of cameras is watched, not
 * scrubbed, and a tile popped out of the wall is a tile the wall no longer
 * shows. `muted` and `playsInline` are what let a tile start on its own,
 * without a click per camera.
 */
function CameraPlayer({
  feed,
  fit,
  showBoxes,
  showZones,
}: {
  feed: CameraFeed
  fit: 'cover' | 'contain'
  showBoxes: boolean
  showZones: boolean
}) {
  const ref = useRef<HTMLVideoElement>(null)
  // The overlay needs the player, not just the video: `playingDate` - the
  // wall-clock instant of the frame on screen, read out of the playlist's
  // EXT-X-PROGRAM-DATE-TIME - is hls.js's, and it is the whole basis of
  // lining a box up with a frame.
  const player = useRef<Hls | undefined>(undefined)
  const source = feed.streamUrl

  // Attaching a media engine to a DOM node is exactly what an Effect is for.
  useEffect(() => {
    const video = ref.current
    if (!video || !source) return

    let cancelled = false
    // hls.js first, native only where it cannot run - which in practice is
    // Safari. Asking `canPlayType('application/vnd.apple.mpegurl')` first
    // looks like the polite check and is a trap: Chromium answers 'maybe',
    // which is truthy, so that branch is taken on a browser that cannot
    // play HLS natively at all. Worse for this app than a black tile, it
    // means hls.js never loads, and hls.js is the only thing that knows
    // `playingDate` - the wall-clock instant of the frame on screen, which
    // is the whole basis of lining a detection box up with it.
    //
    // The import is here rather than at the top of the file so that the
    // tabs with no camera on them never download it.
    void import('hls.js').then(({ default: HlsPlayer }) => {
      if (cancelled) return
      if (!HlsPlayer.isSupported()) {
        video.src = source
        return
      }
      const instance = new HlsPlayer()
      instance.loadSource(source)
      instance.attachMedia(video)
      player.current = instance
    })

    return () => {
      cancelled = true
      player.current?.destroy()
      player.current = undefined
    }
  }, [source])

  if (!source) {
    return (
      <div className="flex size-full items-center justify-center">
        <span className="font-mono text-2xl font-semibold text-border">{feed.id}</span>
      </div>
    )
  }

  return (
    <>
      {/* Absolutely positioned, like the canvas over it. A `size-full` video
          is still a flex item, and its min-content contribution - the
          camera's own 1280x1440 for half of these - beats the tile's
          aspect-video, so the portrait cameras stretched their cards and
          object-cover never cropped anything. Out of flow it cannot. */}
      <video
        ref={ref}
        muted
        autoPlay
        playsInline
        disablePictureInPicture
        className={clsx(
          'absolute inset-0 size-full',
          fit === 'cover' ? 'object-cover' : 'object-contain',
        )}
      />
      {showBoxes || showZones ? (
        <CameraOverlay
          camera={feed.id}
          video={ref}
          player={player}
          fit={fit}
          showBoxes={showBoxes}
          showZones={showZones}
        />
      ) : null}
    </>
  )
}
