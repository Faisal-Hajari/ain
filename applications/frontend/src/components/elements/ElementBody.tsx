import type { ElementResponse } from '@/api/types'
import type { ElementSize } from './ChartFrame'
import { AlertView } from './AlertView'
import { CameraGridView } from './CameraGridView'
import { DonutView } from './DonutView'
import { GaugeView } from './GaugeView'
import { HeatmapView } from './HeatmapView'
import { KpiView } from './KpiView'
import { SeriesView } from './SeriesView'
import { StatGroupView } from './StatGroupView'
import { TableView } from './TableView'

/**
 * The whole rendering decision of the dashboard: a payload type picks a view.
 * Adding an element type means adding a case here and nothing else.
 */
export function ElementBody({ payload, size }: { payload: ElementResponse; size?: ElementSize }) {
  switch (payload.type) {
    case 'kpi':
      return <KpiView data={payload.data} size={size} />
    case 'stat-group':
      return <StatGroupView data={payload.data} size={size} />
    case 'gauge':
      return <GaugeView data={payload.data} />
    case 'line':
    case 'bar':
    case 'stacked-bar':
    case 'histogram':
      return <SeriesView type={payload.type} data={payload.data} size={size} />
    case 'donut':
      return <DonutView data={payload.data} size={size} />
    case 'heatmap':
      return <HeatmapView data={payload.data} />
    case 'alert':
      return <AlertView data={payload.data} />
    case 'table':
      return <TableView data={payload.data} />
    case 'camera-grid':
      return <CameraGridView data={payload.data} />
  }
}
