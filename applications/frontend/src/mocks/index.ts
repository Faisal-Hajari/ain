import type { AlertRuleDraft, Locale } from '@/api/types'
import { createRule, deleteRule, listMonitors, listRules } from './alerts'
import { buildConfig } from './config'
import { buildElementResponse, buildInstanceLog } from './payloads'

/**
 * In-browser stand-in for the backend, used when VITE_API_MOCK=true. It is
 * wired in at the transport layer, so no component or hook knows it exists.
 */
export async function mockRequest(
  method: 'GET' | 'POST' | 'DELETE',
  path: string,
  params: URLSearchParams,
  body?: unknown,
): Promise<unknown> {
  await new Promise((resolve) => setTimeout(resolve, 120 + Math.random() * 240))

  const locale: Locale = params.get('lang') === 'ar' ? 'ar' : 'en'

  // The language must not perturb the generated numbers, or every card would
  // jump when the user switches locale.
  const seed = new URLSearchParams(params)
  seed.delete('lang')
  const seedKey = seed.toString()

  if (method === 'POST' && path === '/alerts/rules') return createRule(body as AlertRuleDraft, locale)

  const rule = /^\/alerts\/rules\/([^/]+)$/.exec(path)
  if (method === 'DELETE' && rule) return deleteRule(rule[1]!)

  if (path === '/dashboard/config') return buildConfig(locale)
  if (path === '/alerts/monitors') return listMonitors(seedKey, locale)
  if (path === '/alerts/rules') return listRules(locale)

  const element = /^\/elements\/([^/]+)$/.exec(path)
  if (element) return buildElementResponse(element[1]!, seedKey, locale)

  const instances = /^\/elements\/([^/]+)\/instances$/.exec(path)
  if (instances) return buildInstanceLog(instances[1]!, seedKey, locale)

  throw new Error(`mock: no handler for ${method} ${path}`)
}
