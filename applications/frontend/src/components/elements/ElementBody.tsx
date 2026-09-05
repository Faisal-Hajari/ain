import type { ElementResponse } from '@/api/types'
import { useLocale } from '@/i18n/LocaleProvider'
import type { ElementSize } from './ChartFrame'
import { CameraGridView } from './CameraGridView'
import { KpiView } from './KpiView'
import { SeriesView } from './SeriesView'
import { StatGroupView } from './StatGroupView'

/**
 * The whole rendering decision of the dashboard: a payload type picks a view.
 * Adding an element type means adding a case here and nothing else.
 */
export function ElementBody({ payload, size }: { payload: ElementResponse; size?: ElementSize }) {
  const { t } = useLocale()

  switch (payload.type) {
    case 'kpi':
      return <KpiView data={payload.data} size={size} />
    case 'stat-group':
      return <StatGroupView data={payload.data} size={size} />
    case 'line':
    case 'histogram':
      return <SeriesView type={payload.type} data={payload.data} size={size} />
    case 'camera-grid':
      return <CameraGridView data={payload.data} />
    // Unreachable per the contract, but `type` is backend JSON: an element type
    // this build does not know about should say so rather than render nothing.
    default:
      return <p className="text-sm text-muted">{t.unsupportedElement}</p>
  }
}
