import type { QueryParams } from '@/api/client'
import { useAlertRules, useDeleteAlertRule } from '@/api/queries'
import { Card, CardBody, CardHeader } from '@/components/ui/Card'
import { Chip } from '@/components/ui/Chip'
import { Skeleton } from '@/components/ui/Skeleton'
import { ErrorState } from '@/components/ui/StateBlocks'
import { useLocale } from '@/i18n/LocaleProvider'

/** The rules the backend holds. Deleting one re-reads the list, never a local copy. */
export function AlertRuleList({ filters }: { filters: QueryParams }) {
  const { t } = useLocale()
  const rules = useAlertRules(filters)
  const remove = useDeleteAlertRule(filters)

  return (
    <Card>
      <CardHeader title={t.yourRules} />
      <CardBody>
        {rules.isPending ? (
          <Skeleton className="h-16 w-full" />
        ) : rules.isError ? (
          <ErrorState message={t.loadFailed} retryLabel={t.retry} onRetry={() => void rules.refetch()} />
        ) : rules.data.rules.length === 0 ? (
          <p className="py-4 text-sm text-muted">{t.noRules}</p>
        ) : (
          <ul className="flex flex-col gap-2">
            {rules.data.rules.map((rule) => (
              <li
                key={rule.id}
                className="flex flex-wrap items-center gap-3 rounded-lg bg-canvas px-3 py-2.5 ring-1 ring-border"
              >
                <span className="text-sm font-medium">{rule.monitorLabel}</span>
                <Chip severity="warn">{rule.summary}</Chip>
                <span className="text-[11px] text-muted">{rule.createdLabel}</span>
                <button
                  type="button"
                  onClick={() => remove.mutate(rule.id)}
                  disabled={remove.isPending}
                  className="ms-auto rounded-md px-2 py-1 text-xs font-medium text-critical ring-1 ring-border hover:bg-surface disabled:opacity-50"
                >
                  {t.deleteRule}
                </button>
              </li>
            ))}
          </ul>
        )}
      </CardBody>
    </Card>
  )
}
