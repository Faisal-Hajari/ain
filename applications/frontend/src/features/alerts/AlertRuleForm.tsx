import type { QueryParams } from '@/api/client'
import { useAlertMonitors, useCreateAlertRule } from '@/api/queries'
import type { AlertComparator, AlertMonitor } from '@/api/types'
import { TrendChart } from '@/components/elements/TrendChart'
import { Card, CardBody, CardHeader } from '@/components/ui/Card'
import { Select } from '@/components/ui/Select'
import { Skeleton } from '@/components/ui/Skeleton'
import { ErrorState } from '@/components/ui/StateBlocks'
import { useUrlParam } from '@/features/filters/useFilters'
import { useLocale } from '@/i18n/LocaleProvider'

/**
 * Build a rule: pick a monitor, pick a direction, set a value. The draft lives
 * in the URL and the saved rule lives in the backend, so this form holds no
 * state of its own.
 */
export function AlertRuleForm({ filters }: { filters: QueryParams }) {
  const { t } = useLocale()
  const monitorParam = useUrlParam('alertMonitor')
  const comparatorParam = useUrlParam('alertDirection')

  const monitors = useAlertMonitors(filters)
  const create = useCreateAlertRule(filters)

  if (monitors.isPending) {
    return (
      <Card>
        <CardHeader title={t.createAlert} />
        <CardBody>
          <Skeleton className="h-24 w-full" />
        </CardBody>
      </Card>
    )
  }

  if (monitors.isError) {
    return (
      <Card>
        <CardHeader title={t.createAlert} />
        <CardBody>
          <ErrorState message={t.loadFailed} retryLabel={t.retry} onRetry={() => void monitors.refetch()} />
        </CardBody>
      </Card>
    )
  }

  const list = monitors.data.monitors
  const selected: AlertMonitor | undefined =
    list.find((monitor) => monitor.id === monitorParam.value) ?? list[0]
  const comparator: AlertComparator = comparatorParam.value === 'below' ? 'below' : 'above'

  const submit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!selected) return
    const form = event.currentTarget
    const threshold = Number(new FormData(form).get('threshold'))
    if (!Number.isFinite(threshold)) return
    create.mutate({ monitorId: selected.id, comparator, threshold }, { onSuccess: () => form.reset() })
  }

  return (
    <Card>
      <CardHeader title={t.createAlert} description={t.createAlertHint} />
      <CardBody>
        <form onSubmit={submit} className="flex flex-col gap-4">
          <div className="flex flex-wrap items-end gap-3">
            <Select
              label={t.monitor}
              value={selected?.id ?? ''}
              options={list.map((monitor) => ({ value: monitor.id, label: monitor.label }))}
              onChange={(value) => monitorParam.set(value)}
            />
            <Select
              label={t.condition}
              value={comparator}
              options={[
                { value: 'above', label: t.above },
                { value: 'below', label: t.below },
              ]}
              onChange={(value) => comparatorParam.set(value)}
            />
            <label className="flex flex-col gap-1">
              <span className="text-[11px] font-medium tracking-wide text-muted uppercase">{t.threshold}</span>
              {/* Uncontrolled, keyed on the monitor: typing stays in the DOM
                  instead of pushing a router navigation per keystroke, and
                  switching monitor remounts the field onto the new suggestion. */}
              <input
                key={selected?.id}
                name="threshold"
                type="number"
                min={0}
                step="any"
                required
                defaultValue={selected?.monthlyAverageValue ?? 0}
                className="w-32 rounded-lg bg-surface px-3 py-2 text-sm text-ink tabular-nums ring-1 ring-border focus:ring-2 focus:ring-brand focus:outline-none"
              />
            </label>
            <button
              type="submit"
              disabled={create.isPending || !selected}
              className="rounded-lg bg-brand px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
            >
              {create.isPending ? t.saving : t.saveAlert}
            </button>
          </div>

          {selected ? (
            <div className="rounded-lg bg-canvas px-4 py-3 ring-1 ring-border">
              <div className="flex flex-wrap items-baseline gap-2">
                <span className="text-[11px] tracking-wide text-muted uppercase">{t.monthlyAverage}</span>
                <span className="text-xl font-semibold tabular-nums">{selected.monthlyAverage}</span>
                <span className="text-xs text-muted">{selected.label}</span>
              </div>
              {selected.trend ? (
                <TrendChart trend={selected.trend} />
              ) : null}
            </div>
          ) : null}

          {create.isError ? <p className="text-sm text-critical">{t.saveFailed}</p> : null}
        </form>
      </CardBody>
    </Card>
  )
}
