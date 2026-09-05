import type { AlertMonitor, AlertRule, AlertRuleDraft, Locale } from '@/api/types'
import { findElement, monitorElements } from './config'
import { monthlyTrend } from './payloads'

/**
 * Alert rules are backend state. The UI never keeps a copy: it POSTs a draft,
 * then re-reads this list. Here that store is an in-memory array; in the real
 * service it is a table.
 */
const rules: AlertRule[] = []

const COMPARATOR: Record<AlertRule['comparator'], Record<Locale, string>> = {
  above: { en: 'Above', ar: 'أعلى من' },
  below: { en: 'Below', ar: 'أدنى من' },
}

const CREATED: Record<Locale, string> = { en: 'Created today', ar: 'أُنشئت اليوم' }

export function listMonitors(seedKey: string, locale: Locale): { monitors: AlertMonitor[] } {
  return {
    monitors: monitorElements(locale).map((element) => {
      const trend = monthlyTrend(element.id, seedKey, locale)
      return {
        id: element.id,
        label: element.title,
        monthlyAverage: trend.averageLabel,
        monthlyAverageValue: trend.average,
        trend: { series: [trend.series], points: trend.points },
      }
    }),
  }
}

/** Rules are rendered in the language they are read in, not the one they were made in. */
function localise(rule: AlertRule, locale: Locale): AlertRule {
  const element = findElement(rule.monitorId, locale)
  return {
    ...rule,
    monitorLabel: element?.title ?? rule.monitorId,
    summary: `${COMPARATOR[rule.comparator][locale]} ${rule.threshold}`,
    createdLabel: CREATED[locale],
  }
}

export function listRules(locale: Locale): { rules: AlertRule[] } {
  return { rules: rules.map((rule) => localise(rule, locale)) }
}

export function createRule(draft: AlertRuleDraft, locale: Locale): AlertRule {
  const element = findElement(draft.monitorId, locale)
  if (!element) throw new Error(`unknown monitor: ${draft.monitorId}`)

  const rule: AlertRule = {
    id: crypto.randomUUID(),
    monitorId: draft.monitorId,
    monitorLabel: element.title,
    comparator: draft.comparator,
    threshold: draft.threshold,
    summary: '',
    createdLabel: '',
  }
  rules.unshift(rule)
  return localise(rule, locale)
}

export function deleteRule(id: string): void {
  const index = rules.findIndex((rule) => rule.id === id)
  if (index >= 0) rules.splice(index, 1)
}
