/**
 * The contract between this dashboard and the backend.
 *
 * The frontend holds no knowledge of what a KPI means: the backend ships a
 * layout (sections -> elements) plus, per element, a payload already shaped for
 * the renderer that its `type` names. Adding a KPI is a backend change.
 */

export type Locale = 'en' | 'ar'

export type ElementType = 'kpi' | 'stat-group' | 'line' | 'histogram' | 'camera-grid'

/**
 * Monitors track a value; alerts count occurrences and open an instance log.
 * The catalogue assigns this per element; the UI only badges it.
 */
export type ElementKind = 'monitor' | 'alert'

/** Refresh cadence, straight from the KPI catalogue. Drives polling only. */
export type UpdateCadence = 'realtime' | 'event' | 'visit' | 'hourly' | 'daily' | 'static'

export type Severity = 'ok' | 'info' | 'warn' | 'critical'

export interface ElementDef {
  id: string
  title: string
  /** One line under the title: what the element measures. */
  description?: string
  type: ElementType
  kind: ElementKind
  updates: UpdateCadence
  /** Grid columns to occupy, 1-4. Defaults to 1. */
  span?: 1 | 2 | 3 | 4
  /** Camera ids feeding this element, shown as chips on the card. */
  cameras?: string[]
  /** When set, the card is clickable and opens that drilldown view. */
  drilldown?: 'instances'
}

/**
 * How a section is presented. 'grid' is the plain card grid; 'alerts' adds the
 * rule builder above the grid. The backend decides, so the nav stays data-driven.
 */
export type SectionView = 'grid' | 'alerts'

export interface SectionDef {
  id: string
  title: string
  description?: string
  view?: SectionView
  elements: ElementDef[]
}

export interface FilterOption {
  value: string
  label: string
}

/**
 * How a filter is presented. 'date-range' renders the preset buttons plus a
 * date input whose picked day becomes the start date; its value is either a
 * preset key or an ISO date.
 */
export type FilterControl = 'select' | 'date-range'

export interface FilterDef {
  /** URL search-param key this filter owns. */
  id: string
  label: string
  control?: FilterControl
  options: FilterOption[]
  defaultValue: string
}

export interface DashboardConfig {
  /** Shown in the nav; already localised for the requested `lang`. */
  branchLabel: string
  /** The backend's today, ISO yyyy-mm-dd. The calendar is drawn from this
   *  rather than the browser clock, which keeps rendering pure. */
  today: string
  filters: FilterDef[]
  sections: SectionDef[]
}

/* ---------------------------------------------------------------- payloads */

export interface Delta {
  /** Already-formatted change, e.g. "+12%". */
  label: string
  direction: 'up' | 'down' | 'flat'
  /** Whether this direction is good news; drives the colour only. */
  sentiment: Severity
}

export interface Point {
  /** Category / time label for the x axis, pre-formatted by the backend. */
  x: string
  [seriesId: string]: string | number
}

export interface SeriesDef {
  id: string
  label: string
  /** Palette slot 0-5; the theme owns the actual colour. */
  colorIndex?: number
}

export interface KpiPayload {
  /** Pre-formatted for display, e.g. "42", "3m 12s", "-". */
  value: string
  unit?: string
  delta?: Delta
  severity?: Severity
  /** Optional trend chart drawn inside the card. */
  trend?: TrendPayload
}

/** The compact chart a card can carry under its headline numbers. */
export interface TrendPayload {
  series: SeriesDef[]
  points: Point[]
}

/** One headline number. A kpi card shows one; a stat-group shows several. */
export interface Stat {
  id: string
  label: string
  /** Pre-formatted for display, e.g. "42", "3m 12s", "-". */
  value: string
  unit?: string
  severity?: Severity
  delta?: Delta
}

export interface StatGroupPayload {
  stats: Stat[]
  /** One line per stat, so the split is readable over time as well as now. */
  trend?: TrendPayload
}

export interface SeriesPayload {
  series: SeriesDef[]
  points: Point[]
  xLabel?: string
  yLabel?: string
  unit?: string
}

export interface CameraFeed {
  id: string
  /** e.g. "Camera 03", already localised. */
  label: string
  zone: string
  status: 'online' | 'offline'
  statusLabel: string
  /** Page the tile plays in an iframe; absent while a feed is down. */
  streamUrl?: string
  thumbnailUrl?: string
}

export interface CameraGridPayload {
  feeds: CameraFeed[]
}

/** Discriminated by the owning element's `type`. */
export type ElementPayload =
  | { type: 'kpi'; data: KpiPayload }
  | { type: 'stat-group'; data: StatGroupPayload }
  | { type: 'line' | 'histogram'; data: SeriesPayload }
  | { type: 'camera-grid'; data: CameraGridPayload }

export type ElementResponse = ElementPayload & {
  elementId: string
  /** ISO timestamp of the underlying data, not of the request. */
  updatedAt: string
}

export interface Instance {
  id: string
  /** Pre-formatted local timestamp. */
  timestamp: string
  camera: string
  detail?: string
  severity?: Severity
  clipUrl?: string
  thumbnailUrl?: string
}

export interface InstanceLog {
  elementId: string
  title: string
  total: number
  instances: Instance[]
}

/* ----------------------------------------------------------------- alerts */

export type AlertComparator = 'above' | 'below'

/** A monitor the user can build an alert rule on. */
export interface AlertMonitor {
  id: string
  label: string
  unit?: string
  /** Pre-formatted 30-day average, e.g. "38" or "4m 12s". */
  monthlyAverage: string
  /** Same average as a number, used to prefill the threshold field. */
  monthlyAverageValue: number
  /** Last 30 days, so the shape is visible while choosing a threshold. */
  trend?: TrendPayload
}

export interface AlertRule {
  id: string
  monitorId: string
  monitorLabel: string
  comparator: AlertComparator
  threshold: number
  unit?: string
  /** Pre-formatted sentence, e.g. "Above 45 people". */
  summary: string
  /** Pre-formatted, e.g. "Created today". */
  createdLabel: string
  /**
   * How the rule has actually done over the window in view. Absent when
   * there is nothing behind the monitor to evaluate it against - which is
   * not the same as zero, and must not print the same way.
   */
  breaches?: number
  /** Pre-formatted, e.g. "Fired 3 times". */
  statusLabel?: string
  severity?: Severity
}

export interface AlertRuleDraft {
  monitorId: string
  comparator: AlertComparator
  threshold: number
}

/* ---------------------------------------------------------------- overlay */

/**
 * One detected object, in coordinates normalised 0..1 against the camera's
 * own frame. Nothing on the wire is in pixels: the tile is whatever size the
 * grid makes it, and the stream may be re-encoded at another resolution.
 */
export interface OverlayObject {
  trackId: number
  label: string
  xc: number
  yc: number
  w: number
  h: number
}

export interface OverlayFrame {
  /** ISO 8601, UTC. The same clock as the HLS EXT-X-PROGRAM-DATE-TIME. */
  ts: string
  objects: OverlayObject[]
}

/** One window of detections, fetched per few seconds rather than per frame. */
export interface OverlayResponse {
  camera: string
  start: string
  end: string
  frames: OverlayFrame[]
}

/** One camera's share of a zone or a counting line. */
export interface GeometryPart {
  camera: string
  name?: string | null
  /** [x, y] pairs, normalised 0..1. */
  points: [number, number][]
}

export interface NamedGeometry {
  name: string
  kind: 'polygon' | 'line'
  /** How many people the zone holds. What a "passed 90%" alert is 90% of. */
  capacity?: number
  parts: GeometryPart[]
}

/** Every zone and line, as configured. Not a measurement: configuration. */
export interface ZonesResponse {
  zones: NamedGeometry[]
  lines: NamedGeometry[]
}
