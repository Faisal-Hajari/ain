import { beforeEach, describe, expect, it, vi } from 'vitest'

/**
 * Loaded per test with the mock transport explicitly off, so the suite does not
 * depend on whatever a local .env.local happens to set.
 */
async function loadClient() {
  vi.stubEnv('VITE_API_MOCK', 'false')
  vi.resetModules()
  return import('./client')
}

function stubFetch(body: unknown, ok = true, status = 200) {
  const fetchMock = vi.fn().mockResolvedValue({ ok, status, json: async () => body })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

describe('apiGet', () => {
  beforeEach(() => {
    vi.unstubAllEnvs()
  })

  it('drops undefined and empty params and sorts the rest', async () => {
    const { apiGet } = await loadClient()
    const fetchMock = stubFetch({})

    await apiGet('/elements/queue-length', { venue: 'cafe', branch: 'olaya', range: undefined, lang: '' })

    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(fetchMock.mock.calls[0]?.[0]).toBe('/api/elements/queue-length?branch=olaya&venue=cafe')
  })

  it('omits the query string entirely when nothing survives', async () => {
    const { apiGet } = await loadClient()
    const fetchMock = stubFetch({})
    await apiGet('/dashboard/config', { lang: undefined })
    expect(fetchMock.mock.calls[0]?.[0]).toBe('/api/dashboard/config')
  })

  it('keeps an ISO date range verbatim', async () => {
    const { apiGet } = await loadClient()
    const fetchMock = stubFetch({})
    await apiGet('/elements/footfall', { range: '2026-09-02' })
    expect(fetchMock.mock.calls[0]?.[0]).toBe('/api/elements/footfall?range=2026-09-02')
  })

  it('raises ApiError carrying the status on a failed response', async () => {
    const { apiGet, ApiError } = await loadClient()
    stubFetch(null, false, 503)
    await expect(apiGet('/dashboard/config')).rejects.toBeInstanceOf(ApiError)
    await expect(apiGet('/dashboard/config')).rejects.toMatchObject({ status: 503 })
  })

  it('sends the body as JSON on a write', async () => {
    const { apiSend } = await loadClient()
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
