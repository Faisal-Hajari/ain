import { describe, expect, it } from 'vitest'
import type { UpdateCadence } from './types'
import { POLL_MS } from './queries'

/**
 * These intervals are published in applications/backend/API.md as the load the
 * backend has to serve. Changing one here without changing the doc is a bug.
 */
describe('POLL_MS', () => {
  it('matches the cadences documented for the backend', () => {
    expect(POLL_MS).toEqual({
      realtime: 15_000,
      event: 60_000,
      visit: 120_000,
      hourly: 300_000,
      daily: 900_000,
      static: false,
    })
  })

  it('covers every cadence the contract allows', () => {
    const cadences: UpdateCadence[] = ['realtime', 'event', 'visit', 'hourly', 'daily', 'static']
    for (const cadence of cadences) expect(POLL_MS).toHaveProperty(cadence)
    expect(Object.keys(POLL_MS)).toHaveLength(cadences.length)
  })
})
