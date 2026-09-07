import type Hls from 'hls.js'
import { useEffect, useMemo, useRef } from 'react'
import { apiGet } from '@/api/client'
import { useZones } from '@/api/queries'
import type { GeometryPart, NamedGeometry, OverlayFrame, OverlayResponse } from '@/api/types'

/**
 * Detection boxes and zone outlines, drawn over a playing camera tile.
 *
 * The boxes are not burnt into the video. Drawing them here is what makes
 * them toggleable per viewer, lets one encoded stream serve everybody, and
 * costs no GPU - the pipeline deliberately encodes nothing.
 *
 * Lining them up with the frame on screen works because of two clocks that
 * are really one. The stored detections carry absolute timestamps, and every
 * HLS segment carries EXT-X-PROGRAM-DATE-TIME, which hls.js exposes as
 * `playingDate`: the wall-clock instant of the frame actually being shown.
 * The latency ordering does the rest, and it is tighter than it looks.
 * Measured on this stack: the newest HLS segment is ~1.6s behind real time
 * and the newest detection ~3.2s, so at the server edge the metadata is
 * BEHIND. What saves it is the player: hls.js starts three segments back
 * from the live edge, putting the frame on screen ~5.2s old against boxes
 * 3.2s old - about two seconds of margin, and all of it comes from that
 * buffer rather than from the pipeline being quick.
 *
 * Two things eat that margin, and both were measured doing it: VBV rate
 * control on the transcode (-maxrate/-bufsize) delayed the frame the
 * adapter saw by ~2s relative to the segment MediaMTX stamped, and a
 * nvstreammux batch_size matched to the camera count cost another 2.4s.
 * Neither shows up as a queue anywhere - they are clock offsets, not
 * backlogs, so the only way to see them is to compare the two paths.
 */

/** How much video each fetch covers. One request per camera per few seconds. */
const WINDOW_MS = 5_000
/** Refetched slightly before the window runs out, so there is no gap. */
const REFETCH_MS = 3_500
/** Past this, the nearest stored frame is not this frame and nothing is drawn. */
const MATCH_TOLERANCE_MS = 200

const BOX_STROKE = '#3ddc84'
const BOX_LABEL_BG = 'rgba(0, 0, 0, 0.65)'
const ZONE_STROKE = 'rgba(96, 165, 250, 0.9)'
const ZONE_FILL = 'rgba(96, 165, 250, 0.12)'
const LINE_STROKE = 'rgba(251, 191, 36, 0.95)'

/**
 * The wall-clock instant of the frame on screen, or null.
 *
 * hls.js reads it off the playlist. Safari plays HLS natively and does not,
 * so there it is reconstructed from the stream's start date plus how far
 * into it the video has played.
 */
function playingDate(video: HTMLVideoElement, player: Hls | undefined): Date | null {
  const fromPlayer = player?.playingDate
  if (fromPlayer instanceof Date) return fromPlayer
  const start = (video as HTMLVideoElement & { getStartDate?: () => Date }).getStartDate?.()
  if (start instanceof Date && !Number.isNaN(start.getTime())) {
    return new Date(start.getTime() + video.currentTime * 1000)
  }
  return null
}

/**
 * Where the video's own pixels actually sit inside the element.
 *
 * A tile is 16:9 and several of these cameras are 1280x1440, so `object-fit`
 * is either cropping or letterboxing every frame. Boxes are normalised
 * against the source frame, so drawing them against the element's box rather
 * than the video's content box puts every one of them in the wrong place.
 */
export function contentBox(video: Pick<HTMLVideoElement, 'videoWidth' | 'videoHeight'>, width: number, height: number, fit: 'cover' | 'contain') {
  const { videoWidth, videoHeight } = video
  if (!videoWidth || !videoHeight) return null
  const ratio =
    fit === 'cover'
      ? Math.max(width / videoWidth, height / videoHeight)
      : Math.min(width / videoWidth, height / videoHeight)
  const drawnWidth = videoWidth * ratio
  const drawnHeight = videoHeight * ratio
  return {
    left: (width - drawnWidth) / 2,
    top: (height - drawnHeight) / 2,
    width: drawnWidth,
    height: drawnHeight,
  }
}

/** A window of detections with its timestamps already parsed. */
export interface Window {
  frames: OverlayFrame[]
  /** Milliseconds per frame, ascending, index-aligned with `frames`. */
  times: number[]
}

/**
 * Parses a fetched window once, so the draw loop never has to.
 *
 * The server returns frames in time order, which is what lets the lookup
 * below be a binary search.
 */
export function toWindow(frames: OverlayFrame[]): Window {
  return { frames, times: frames.map((frame) => Date.parse(frame.ts)) }
}

/**
 * The stored frame nearest an instant, or null when none is close enough.
 *
 * Exported, with `contentBox`, because between them they are the whole of
 * what puts a box in the right place: everything else in this file is
 * plumbing, and these two are worth a test.
 *
 * A binary search over pre-parsed times rather than a scan that re-parses
 * every timestamp: this runs once per animation frame per tile, so at nine
 * tiles and 60 fps a linear pass was ~40 000 Date.parse calls a second.
 */
export function nearestFrame(window: Window, at: number): OverlayFrame | null {
  const { times, frames } = window
  if (!times.length) return null

  let low = 0
  let high = times.length - 1
  while (low < high) {
    const mid = (low + high) >> 1
    if (times[mid]! < at) low = mid + 1
    else high = mid
  }
  // `low` is the first frame at or after `at`; its neighbour may be closer.
  // A tie goes to the earlier frame: its boxes were in the database before
  // the instant being drawn, which the later one's were not.
  let best = low
  if (low > 0 && Math.abs(times[low - 1]! - at) <= Math.abs(times[low]! - at)) {
    best = low - 1
  }
  return Math.abs(times[best]! - at) <= MATCH_TOLERANCE_MS ? frames[best]! : null
}

/** Every part of every zone and line that belongs to one camera. */
function partsFor(shapes: NamedGeometry[], camera: string): { shape: NamedGeometry; part: GeometryPart }[] {
  return shapes.flatMap((shape) =>
    shape.parts.filter((part) => part.camera === camera).map((part) => ({ shape, part })),
  )
}

export function CameraOverlay({
  camera,
  video,
  player,
  fit,
  showBoxes,
  showZones,
}: {
  camera: string
  video: React.RefObject<HTMLVideoElement | null>
  player: React.RefObject<Hls | undefined>
  fit: 'cover' | 'contain'
  showBoxes: boolean
  showZones: boolean
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const frames = useRef<Window>({ frames: [], times: [] })
  const zones = useZones({ enabled: showZones })
  const shapes = zones.data
  const geometry = useMemo(
    () =>
      shapes && showZones
        ? [...partsFor(shapes.zones, camera), ...partsFor(shapes.lines, camera)]
        : [],
    [camera, shapes, showZones],
  )

  // One request per window of video, not per frame: at 15 fps a five-second
  // window is ~75 frames and a few hundred boxes, which is tens of kilobytes.
  useEffect(() => {
    if (!showBoxes) {
      frames.current = toWindow([])
      return
    }
    let cancelled = false

    const fetchWindow = async () => {
      const element = video.current
      if (!element) return
      const at = playingDate(element, player.current)
      if (!at) return
      try {
        const body = await apiGet<OverlayResponse>('/overlay', {
          camera,
          // A second of slack behind: the frame on screen when the request
          // is answered is a little later than the one when it was made.
          start: new Date(at.getTime() - 1_000).toISOString(),
          end: new Date(at.getTime() + WINDOW_MS).toISOString(),
        })
        if (!cancelled) frames.current = toWindow(body.frames)
      } catch {
        // No detections for this camera yet, or the analytics service is
        // still starting. A tile with no boxes is the correct rendering of
        // "nothing to draw"; an error message over live video is not.
        if (!cancelled) frames.current = toWindow([])
      }
    }

    void fetchWindow()
    const timer = window.setInterval(() => void fetchWindow(), REFETCH_MS)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [camera, player, showBoxes, video])

  // Redrawn every animation frame, because the video advances every frame and
  // a box a frame behind is a box in the wrong place.
  useEffect(() => {
    let request = 0

    const draw = () => {
      request = requestAnimationFrame(draw)
      const canvas = canvasRef.current
      const element = video.current
      if (!canvas || !element) return

      const width = element.clientWidth
      const height = element.clientHeight
      if (!width || !height) return
      const scale = window.devicePixelRatio || 1
      if (canvas.width !== Math.round(width * scale) || canvas.height !== Math.round(height * scale)) {
        canvas.width = Math.round(width * scale)
        canvas.height = Math.round(height * scale)
      }

      const context = canvas.getContext('2d')
      if (!context) return
      context.setTransform(scale, 0, 0, scale, 0, 0)
      context.clearRect(0, 0, width, height)

      const box = contentBox(element, width, height, fit)
      if (!box) return

      for (const { shape, part } of geometry) {
        drawShape(context, box, shape, part)
      }

      if (!showBoxes) return
      const at = playingDate(element, player.current)
      if (!at) return
      const frame = nearestFrame(frames.current, at.getTime())
      if (!frame) return

      context.lineWidth = 2
      context.strokeStyle = BOX_STROKE
      context.font = '11px ui-monospace, monospace'
      for (const object of frame.objects) {
        const left = box.left + (object.xc - object.w / 2) * box.width
        const top = box.top + (object.yc - object.h / 2) * box.height
        const boxWidth = object.w * box.width
        const boxHeight = object.h * box.height
        context.strokeRect(left, top, boxWidth, boxHeight)
        const label = `${object.label} ${object.trackId}`
        const text = context.measureText(label)
        context.fillStyle = BOX_LABEL_BG
        context.fillRect(left, Math.max(0, top - 14), text.width + 6, 14)
        context.fillStyle = BOX_STROKE
        context.fillText(label, left + 3, Math.max(10, top - 3))
      }
    }

    request = requestAnimationFrame(draw)
    return () => cancelAnimationFrame(request)
  }, [fit, geometry, player, showBoxes, video])

  return (
    <canvas
      ref={canvasRef}
      aria-hidden
      className="pointer-events-none absolute inset-0 size-full"
    />
  )
}

/** Strokes one zone polygon or counting line onto the canvas. */
function drawShape(
  context: CanvasRenderingContext2D,
  box: { left: number; top: number; width: number; height: number },
  shape: NamedGeometry,
  part: GeometryPart,
) {
  const first = part.points[0]
  if (!first || part.points.length < 2) return
  context.beginPath()
  part.points.forEach(([x, y], index) => {
    const pointX = box.left + x * box.width
    const pointY = box.top + y * box.height
    if (index === 0) context.moveTo(pointX, pointY)
    else context.lineTo(pointX, pointY)
  })
  if (shape.kind === 'polygon') {
    context.closePath()
    context.fillStyle = ZONE_FILL
    context.fill()
    context.strokeStyle = ZONE_STROKE
  } else {
    context.strokeStyle = LINE_STROKE
  }
  context.lineWidth = 2
  context.stroke()

  context.fillStyle = shape.kind === 'polygon' ? ZONE_STROKE : LINE_STROKE
  context.font = '11px ui-monospace, monospace'
  context.fillText(
    part.name && part.name !== shape.name ? `${shape.name}/${part.name}` : shape.name,
    box.left + first[0] * box.width + 4,
    box.top + first[1] * box.height + 12,
  )
}
