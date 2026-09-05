import type { AlertPayload } from '@/api/types'
import { Chip } from '@/components/ui/Chip'
import { severityText } from '@/components/ui/severity'
import { useLocale } from '@/i18n/LocaleProvider'
import { severityLabel } from '@/i18n/dictionary'

export function AlertView({ data }: { data: AlertPayload }) {
  const { t } = useLocale()

  return (
    <div className="flex flex-1 flex-col gap-2">
      <div className="flex items-center gap-2">
        <span className={`text-lg font-semibold ${severityText[data.severity]}`}>{data.headline}</span>
        <Chip severity={data.severity}>{severityLabel(t, data.severity)}</Chip>
      </div>
      {data.detail ? <p className="text-xs text-muted">{data.detail}</p> : null}
      {data.meta ? <p className="mt-auto text-[11px] text-muted">{data.meta}</p> : null}
    </div>
  )
}
