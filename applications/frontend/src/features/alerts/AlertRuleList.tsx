import type { QueryParams } from '@/api/client'
import { useAlertRules, useDeleteAlertRule } from '@/api/queries'
import { Card, CardBody, CardHeader } from '@/components/ui/Card'
import { Chip } from '@/components/ui/Chip'
import { Skeleton } from '@/components/ui/Skeleton'
import { ErrorState } from '@/components/ui/StateBlocks'
import { useUrlParam } from '@/features/filters/useFilters'
import { useLocale } from '@/i18n/LocaleProvider'

/** The rules the backend holds. Deleting one re-reads the list, never a local copy. */
export function AlertRuleList({ filters }: { filters: QueryParams }) {
  const { t } = useLocale()
  const rules = useAlertRules(filters)
  const remove = useDeleteAlertRule(filters)
  // Deleting is irreversible and one click from a hover, so it asks first.
  const pending = useUrlParam('confirmDelete')

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
                {pending.value === rule.id ? (
                  <span className="ms-auto flex items-center gap-2">
                    <span className="text-xs text-muted">{t.confirmDelete}</span>
                    <button
                      type="button"
                      onClick={() => {
                        pending.set(null)
                        remove.mutate(rule.id)
                      }}
                      disabled={remove.isPending}
                      className="rounded-md px-2 py-1 text-xs font-medium text-critical ring-1 ring-critical/40 hover:bg-critical/10 disabled:opacity-50"
                    >
                      {t.confirm}
                    </button>
                    <button
                      type="button"
                      onClick={() => pending.set(null)}
                      className="rounded-md px-2 py-1 text-xs font-medium text-muted ring-1 ring-border hover:bg-surface"
                    >
                      {t.cancel}
                    </button>
                  </span>
                ) : (
                  <button
                    type="button"
                    onClick={() => pending.set(rule.id)}
                    className="ms-auto rounded-md px-2 py-1 text-xs font-medium text-critical ring-1 ring-border hover:bg-surface"
                  >
                    {t.deleteRule}
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
      </CardBody>
    </Card>
  )
}
