import { describe, expect, it } from 'vitest'
import { contentBox, nearestFrame } from './CameraOverlay'
import type { OverlayFrame } from '@/api/types'

/**
 * The two calculations that decide whether a box lands on the person or
 * somewhere else on the tile.
 */

const portrait = { videoWidth: 1280, videoHeight: 1440 }
const landscape = { videoWidth: 1280, videoHeight: 720 }

describe('contentBox', () => {
  it('fills the element when the aspect ratios already agree', () => {
    const box = contentBox(landscape, 640, 360, 'cover')
    expect(box).toEqual({ left: 0, top: 0, width: 640, height: 360 })
  })

  it('crops a portrait camera into a 16:9 tile', () => {
    // The grid is 16:9 and several of these cameras are 1280x1440, so
    // object-cover throws away the top and bottom. Drawing against the
    // element's box instead of the video's would squash every box.
    const box = contentBox(portrait, 640, 360, 'cover')!
    expect(box.width).toBe(640)
    expect(box.height).toBeCloseTo(720)
    expect(box.top).toBeCloseTo(-180)
    expect(box.left).toBe(0)
  })

  it('letterboxes the same camera when the dialog contains it', () => {
    const box = contentBox(portrait, 640, 360, 'contain')!
    expect(box.height).toBe(360)
    expect(box.width).toBeCloseTo(320)
    expect(box.left).toBeCloseTo(160)
    expect(box.top).toBe(0)
  })

  it('answers null before the video knows its own size', () => {
    expect(contentBox({ videoWidth: 0, videoHeight: 0 }, 640, 360, 'cover')).toBeNull()
  })
})

describe('nearestFrame', () => {
  const frames: OverlayFrame[] = [
    { ts: '2026-09-06T21:00:00.000Z', objects: [] },
    { ts: '2026-09-06T21:00:00.400Z', objects: [] },
    { ts: '2026-09-06T21:00:01.000Z', objects: [] },
  ]

  it('picks the closest stored frame to the one on screen', () => {
    const at = Date.parse('2026-09-06T21:00:00.450Z')
    expect(nearestFrame(frames, at)?.ts).toBe('2026-09-06T21:00:00.400Z')
  })

  it('draws nothing when the nearest frame is too far away', () => {
    // A gap this size means the pipeline missed that stretch of video.
    // Drawing the neighbouring frame's boxes anyway would put them where
    // people used to be.
    const at = Date.parse('2026-09-06T21:00:05.000Z')
    expect(nearestFrame(frames, at)).toBeNull()
  })

  it('draws nothing before the first window has arrived', () => {
    expect(nearestFrame([], Date.now())).toBeNull()
  })
})
