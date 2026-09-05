import { describe, expect, it, vi } from 'vitest'
import { ApiError, apiGet, apiSend } from './client'

function stubFetch(body: unknown, ok = true, status = 200) {
  const fetchMock = vi.fn().mockResolvedValue({ ok, status, json: async () => body })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

describe('apiGet', () => {
  it('drops undefined and empty params and sorts the rest', async () => {
    const fetchMock = stubFetch({})

    await apiGet('/elements/queue-length', { venue: 'cafe', branch: 'olaya', range: undefined, lang: '' })

    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(fetchMock.mock.calls[0]?.[0]).toBe('/api/elements/queue-length?branch=olaya&venue=cafe')
  })

  it('omits the query string entirely when nothing survives', async () => {
    const fetchMock = stubFetch({})
    await apiGet('/dashboard/config', { lang: undefined })
    expect(fetchMock.mock.calls[0]?.[0]).toBe('/api/dashboard/config')
  })

  it('keeps an ISO date range verbatim', async () => {
    const fetchMock = stubFetch({})
    await apiGet('/elements/footfall', { range: '2026-09-02' })
    expect(fetchMock.mock.calls[0]?.[0]).toBe('/api/elements/footfall?range=2026-09-02')
  })

  it('raises ApiError carrying the status on a failed response', async () => {
    stubFetch(null, false, 503)
    await expect(apiGet('/dashboard/config')).rejects.toBeInstanceOf(ApiError)
    await expect(apiGet('/dashboard/config')).rejects.toMatchObject({ status: 503 })
  })

  it('sends the body as JSON on a write', async () => {
    const fetchMock = stubFetch({ id: 'r1' })

    await apiSend('POST', '/alerts/rules', { monitorId: 'queue-length', comparator: 'above', threshold: 4 }, { lang: 'ar' })

    const [url, init] = fetchMock.mock.calls[0] ?? []
    expect(url).toBe('/api/alerts/rules?lang=ar')
    expect(init).toMatchObject({ method: 'POST' })
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({
      monitorId: 'queue-length',
      comparator: 'above',
      threshold: 4,
    })
  })
})
