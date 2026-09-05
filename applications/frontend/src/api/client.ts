import { mockRequest } from '@/mocks'

const BASE_URL = '/api'
const USE_MOCKS = import.meta.env.VITE_API_MOCK === 'true'

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status?: number,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

export type QueryParams = Record<string, string | undefined>

function toSearchParams(params: QueryParams = {}): URLSearchParams {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== '') search.set(key, value)
  }
  search.sort()
  return search
}

/** The single place the app talks to the network. */
export async function apiGet<T>(path: string, params?: QueryParams, signal?: AbortSignal): Promise<T> {
  const search = toSearchParams(params)

  if (USE_MOCKS) return (await mockRequest('GET', path, search)) as T

  const query = search.toString()
  const response = await fetch(`${BASE_URL}${path}${query ? `?${query}` : ''}`, {
    signal,
    headers: { Accept: 'application/json' },
  })
  if (!response.ok) throw new ApiError(`GET ${path} failed`, response.status)
  return (await response.json()) as T
}

/**
 * Writes. The app keeps no state of its own, so a mutation's only job is to
 * tell the backend and then let the affected queries refetch.
 */
export async function apiSend<T>(
  method: 'POST' | 'DELETE',
  path: string,
  body?: unknown,
  params?: QueryParams,
): Promise<T> {
  const search = toSearchParams(params)

  if (USE_MOCKS) return (await mockRequest(method, path, search, body)) as T

  const query = search.toString()
  const response = await fetch(`${BASE_URL}${path}${query ? `?${query}` : ''}`, {
    method,
    headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!response.ok) throw new ApiError(`${method} ${path} failed`, response.status)
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}
