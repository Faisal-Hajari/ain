import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiGet, apiSend, type QueryParams } from './client'
import type {
  AlertMonitor,
  AlertRule,
  AlertRuleDraft,
  DashboardConfig,
  ElementDef,
  ElementResponse,
  InstanceLog,
  Locale,
  UpdateCadence,
} from './types'

/** How often a card re-asks the backend, by the cadence the catalogue gives it. */
export const POLL_MS: Record<UpdateCadence, number | false> = {
  realtime: 15_000,
  event: 60_000,
  visit: 120_000,
  hourly: 300_000,
  daily: 900_000,
  static: false,
}

export function useDashboardConfig(locale: Locale) {
  return useQuery({
    queryKey: ['dashboard-config', locale],
    queryFn: ({ signal }) => apiGet<DashboardConfig>('/dashboard/config', { lang: locale }, signal),
    staleTime: 5 * 60_000,
  })
}

export function useElementData(element: ElementDef, filters: QueryParams) {
  return useQuery({
    queryKey: ['element', element.id, filters],
    queryFn: ({ signal }) => apiGet<ElementResponse>(`/elements/${element.id}`, filters, signal),
    refetchInterval: POLL_MS[element.updates],
    staleTime: 10_000,
  })
}

export function useInstanceLog(elementId: string | null, filters: QueryParams) {
  return useQuery({
    queryKey: ['instances', elementId, filters],
    queryFn: ({ signal }) => apiGet<InstanceLog>(`/elements/${elementId}/instances`, filters, signal),
    enabled: elementId !== null,
  })
}

/** Monitors an alert can be built on, each with its 30-day average. */
export function useAlertMonitors(filters: QueryParams) {
  return useQuery({
    queryKey: ['alert-monitors', filters],
    queryFn: ({ signal }) => apiGet<{ monitors: AlertMonitor[] }>('/alerts/monitors', filters, signal),
    staleTime: 5 * 60_000,
  })
}

export function useAlertRules(filters: QueryParams) {
  return useQuery({
    queryKey: ['alert-rules', filters],
    queryFn: ({ signal }) => apiGet<{ rules: AlertRule[] }>('/alerts/rules', filters, signal),
  })
}

export function useCreateAlertRule(filters: QueryParams) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (draft: AlertRuleDraft) => apiSend<AlertRule>('POST', '/alerts/rules', draft, filters),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['alert-rules'] }),
  })
}

export function useDeleteAlertRule(filters: QueryParams) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (ruleId: string) => apiSend<void>('DELETE', `/alerts/rules/${ruleId}`, undefined, filters),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['alert-rules'] }),
  })
}
