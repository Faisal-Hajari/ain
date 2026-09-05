import type {
  ElementDef,
  ElementResponse,
  Instance,
  InstanceLog,
  Locale,
  Point,
  Severity,
} from '@/api/types'
import { findElement } from './config'

/**
 * Deterministic fake data for `GET /api/elements/:id`. Same element id + same
 * filters always produce the same payload, so the UI never flickers between
 * renders and screenshots stay comparable. The seed excludes the language, so
 * switching locale re-labels a card without moving its numbers.
 *
 * Every element type in the contract is covered here, including the ones no
 * element currently uses - this doubles as the payload reference the backend
 * has to match.
 */

type Text = Record<Locale, string>

const t = (text: Text, locale: Locale) => text[locale]

/** xmur3-seeded mulberry32: small, stable, and dependency-free. */
function makeRandom(seed: string): () => number {
  let h = 1779033703 ^ seed.length
  for (let i = 0; i < seed.length; i += 1) {
    h = Math.imul(h ^ seed.charCodeAt(i), 3432918353)
    h = (h << 13) | (h >>> 19)
  }
  let a = h >>> 0
  return () => {
    a = (a + 0x6d2b79f5) | 0
    let x = Math.imul(a ^ (a >>> 15), 1 | a)
    x = (x + Math.imul(x ^ (x >>> 7), 61 | x)) ^ x
    return ((x ^ (x >>> 14)) >>> 0) / 4294967296
  }
}

const between = (rand: () => number, min: number, max: number) => min + rand() * (max - min)
const intBetween = (rand: () => number, min: number, max: number) => Math.round(between(rand, min, max))

const HOURS = ['08', '09', '10', '11', '12', '13', '14', '15', '16', '17', '18', '19', '20', '21']

const DAYS: Text[] = [
  { en: 'Mon', ar: 'الإثنين' },
  { en: 'Tue', ar: 'الثلاثاء' },
  { en: 'Wed', ar: 'الأربعاء' },
  { en: 'Thu', ar: 'الخميس' },
  { en: 'Fri', ar: 'الجمعة' },
  { en: 'Sat', ar: 'السبت' },
  { en: 'Sun', ar: 'الأحد' },
]

const LABELS = {
  hour: { en: 'Hour', ar: 'الساعة' },
  day: { en: 'Day', ar: 'اليوم' },
  count: { en: 'Count', ar: 'العدد' },
  minutes: { en: 'Minutes', ar: 'الدقائق' },
  visits: { en: 'Visits', ar: 'الزيارات' },
  people: { en: 'people', ar: 'شخص' },
  total: { en: 'Total', ar: 'الإجمالي' },
  indoor: { en: 'Indoor', ar: 'الداخلي' },
  outdoor: { en: 'Outdoor', ar: 'الخارجي' },
  camera: { en: 'Camera', ar: 'كاميرا' },
  online: { en: 'Online', ar: 'متصلة' },
  offline: { en: 'No signal', ar: 'لا إشارة' },
  feedsOnline: { en: 'Online', ar: 'متصلة' },
  feedsOffline: { en: 'No signal', ar: 'غير متصلة' },
  noAlert: { en: 'No active alert', ar: 'لا يوجد تنبيه نشط' },
  approaching: { en: 'Threshold approaching', ar: 'اقتراب من الحد' },
  activeNow: { en: 'Active now', ar: 'نشط الآن' },
  since: { en: 'since', ar: 'منذ' },
  lastFlagged: { en: 'Last flagged 2h ago', ar: 'آخر رصد قبل ساعتين' },
  day30: { en: 'D-', ar: 'ي-' },
} satisfies Record<string, Text>

/** Durations are formatted server-side, so the card just prints the string. */
function duration(minutes: number, seconds: number, locale: Locale): string {
  return locale === 'ar' ? `${minutes} د ${seconds} ث` : `${minutes}m ${seconds}s`
}

/**
 * The range filter carries either a preset key or an ISO start date. A custom
 * start is bucketed by how far back it reaches.
 */
function resolveRange(seedKey: string): 'today' | '7d' | '30d' {
  if (seedKey.includes('range=30d')) return '30d'
  if (seedKey.includes('range=7d')) return '7d'

  const custom = /range=(\d{4}-\d{2}-\d{2})/.exec(seedKey)
  if (custom) {
    const days = Math.round((Date.parse(new Date().toISOString().slice(0, 10)) - Date.parse(custom[1]!)) / 86_400_000)
    if (days >= 8) return '30d'
    if (days >= 1) return '7d'
  }
  return 'today'
}

function xAxis(range: string, locale: Locale): string[] {
  if (range === '30d') return Array.from({ length: 30 }, (_, i) => `${t(LABELS.day30, locale)}${29 - i}`)
  if (range === '7d') return DAYS.map((day) => t(day, locale))
  return HOURS.map((hour) => `${hour}:00`)
}

function severityFor(rand: () => number): Severity {
  const roll = rand()
  if (roll > 0.88) return 'critical'
  if (roll > 0.65) return 'warn'
  return 'ok'
}

function trendPoints(rand: () => number, labels: string[], seriesId: string, min: number, max: number): Point[] {
  let value = between(rand, min, max)
  return labels.map((label) => {
    value = Math.min(max, Math.max(min, value + between(rand, -(max - min) / 4, (max - min) / 4)))
    return { x: label, [seriesId]: Math.round(value) }
  })
}

function deltaFor(points: Point[], seriesId: string, isAlert: boolean) {
  const last = Number(points[points.length - 1]?.[seriesId] ?? 0)
  const first = Number(points[0]?.[seriesId] ?? 0)
  const changed = first === 0 ? 0 : Math.round(((last - first) / first) * 100)
  return {
    value: last,
    delta: {
      label: `${changed > 0 ? '+' : ''}${changed}%`,
      direction: changed > 0 ? ('up' as const) : changed < 0 ? ('down' as const) : ('flat' as const),
      // Rising counts are bad news for an alert and unremarkable for a monitor.
      sentiment: isAlert
        ? changed > 0
          ? ('critical' as const)
          : ('ok' as const)
        : changed < 0
          ? ('warn' as const)
          : ('ok' as const),
    },
  }
}

/** Minutes-and-seconds elements read as a duration; the rest are plain counts. */
const isDuration = (id: string) => id.includes('time') || id.includes('hours')

const STAFF = ['A. Nasser', 'M. Saleh', 'R. Kumar', 'L. Haddad', 'S. Otieno', 'F. Aziz']

// A list, not a keyed object: '10' is an integer-like key and would sort itself
// ahead of '03' in Object.entries.
const CAMERA_COVERAGE: [camera: string, zone: Text][] = [
  ['03', { en: 'Indoor entrance and lobby / waiting area.', ar: 'المدخل الداخلي والبهو / منطقة الانتظار.' }],
  ['04', { en: 'Indoor seating area (high-top tables).', ar: 'منطقة الجلوس الداخلية (طاولات مرتفعة).' }],
  ['05', { en: 'Back-of-house kitchen - fryer line and hot-food prep.', ar: 'مطبخ المؤخرة - خط القلي وتحضير الطعام الساخن.' }],
  ['06', { en: 'Outdoor street frontage and parking bays.', ar: 'واجهة الشارع ومواقف السيارات.' }],
  ['07', { en: 'Outdoor parking area and street frontage.', ar: 'منطقة المواقف الخارجية وواجهة الشارع.' }],
  ['10', { en: 'Outdoor rear / side parking and lane.', ar: 'المواقف الخلفية / الجانبية والممر.' }],
  ['11', { en: 'Register / POS and cashier station.', ar: 'الصندوق ونقطة البيع ومحطة الكاشير.' }],
  ['12', { en: 'Service counter and hot-food display.', ar: 'كاونتر الخدمة وعرض الطعام الساخن.' }],
  ['13', { en: 'Back-of-house storage and utility corridor.', ar: 'مخزن المؤخرة وممر الخدمات.' }],
  ['15', { en: 'Rear service alley and delivery / back door.', ar: 'ممر الخدمة الخلفي وباب التوصيل.' }],
]

function tablePayload(id: string, rand: () => number, locale: Locale) {
  if (id === 'camera-coverage') {
    return {
      columns: [
        { key: 'camera', label: t(LABELS.camera, locale) },
        { key: 'zone', label: locale === 'ar' ? 'منطقة التغطية' : 'Coverage zone' },
      ],
      rows: CAMERA_COVERAGE.map(([camera, zone]) => ({
        camera: `${t(LABELS.camera, locale)} ${camera}`,
        zone: t(zone, locale),
      })),
    }
  }
  return {
    columns: [
      { key: 'staff', label: locale === 'ar' ? 'الموظف' : 'Staff' },
      { key: 'hours', label: locale === 'ar' ? 'ساعات العمل' : 'Hours worked', align: 'end' as const },
    ],
    rows: STAFF.map((staff) => ({ staff, hours: duration(intBetween(rand, 6, 10) * 60, 0, locale) })),
  }
}

export function buildElementResponse(id: string, seedKey: string, locale: Locale): ElementResponse {
  const element: ElementDef | undefined = findElement(id, locale)
  if (!element) throw new Error(`unknown element: ${id}`)

  const rand = makeRandom(`${id}|${seedKey}`)
  const range = resolveRange(seedKey)
  const labels = xAxis(range, locale)
  const isAlert = element.kind === 'alert'
  const base = { elementId: id, updatedAt: new Date().toISOString() }

  switch (element.type) {
    case 'kpi': {
      const points = trendPoints(rand, labels.slice(-12), 'value', isDuration(id) ? 1 : 0, isDuration(id) ? 14 : 24)
      const { value, delta } = deltaFor(points, 'value', isAlert)
      return {
        ...base,
        type: 'kpi',
        data: {
          value: isDuration(id) ? duration(value, intBetween(rand, 0, 59), locale) : String(value),
          severity: isAlert ? severityFor(rand) : 'ok',
          delta,
          trend: { series: [{ id: 'value', label: element.title, colorIndex: 0 }], points },
        },
      }
    }
    case 'stat-group': {
      if (id === 'camera-status') {
        const statuses = CAMERA_COVERAGE.map(() => rand() > 0.12)
        const online = statuses.filter(Boolean).length
        return {
          ...base,
          type: 'stat-group',
          data: {
            stats: [
              { id: 'total', label: t(LABELS.total, locale), value: String(statuses.length) },
              { id: 'online', label: t(LABELS.feedsOnline, locale), value: String(online), severity: 'ok' },
              {
                id: 'offline',
                label: t(LABELS.feedsOffline, locale),
                value: String(statuses.length - online),
                severity: online === statuses.length ? 'ok' : 'critical',
              },
            ],
          },
        }
      }

      const totals = trendPoints(rand, labels.slice(-12), 'total', 8, 60)
      // Indoor is a share of each total and outdoor is the remainder, so the
      // three lines always add up the way the three numbers do.
      const points: Point[] = totals.map((point) => {
        const total = Number(point.total ?? 0)
        const indoorAt = Math.round(total * between(rand, 0.55, 0.75))
        return { x: String(point.x), total, indoor: indoorAt, outdoor: total - indoorAt }
      })
      const latest = points[points.length - 1]
      const { delta } = deltaFor(points, 'total', isAlert)
      return {
        ...base,
        type: 'stat-group',
        data: {
          stats: [
            { id: 'total', label: t(LABELS.total, locale), value: String(latest?.total ?? 0), delta },
            { id: 'indoor', label: t(LABELS.indoor, locale), value: String(latest?.indoor ?? 0) },
            { id: 'outdoor', label: t(LABELS.outdoor, locale), value: String(latest?.outdoor ?? 0) },
          ],
          trend: {
            series: [
              { id: 'total', label: t(LABELS.total, locale), colorIndex: 0 },
              { id: 'indoor', label: t(LABELS.indoor, locale), colorIndex: 1 },
              { id: 'outdoor', label: t(LABELS.outdoor, locale), colorIndex: 2 },
            ],
            points,
          },
        },
      }
    }
    case 'gauge': {
      const value = intBetween(rand, 35, 96)
      return {
        ...base,
        type: 'gauge',
        data: {
          value,
          min: 0,
          max: 100,
          unit: '%',
          valueLabel: `${value}%`,
          minLabel: '0%',
          maxLabel: '100%',
          severity: value > 90 ? 'critical' : value > 75 ? 'warn' : 'ok',
        },
      }
    }
    case 'line':
    case 'histogram': {
      const isHistogram = element.type === 'histogram'
      const buckets = isHistogram ? ['0-10', '10-20', '20-30', '30-45', '45-60', '60+'] : labels
      return {
        ...base,
        type: element.type,
        data: {
          series: [
            {
              id: 'value',
              label: isHistogram ? t(LABELS.visits, locale) : element.title,
              colorIndex: 0,
            },
          ],
          points: trendPoints(rand, buckets, 'value', 4, isHistogram ? 90 : 140),
          xLabel: isHistogram
            ? t(LABELS.minutes, locale)
            : range === 'today'
              ? t(LABELS.hour, locale)
              : t(LABELS.day, locale),
          yLabel: isHistogram ? t(LABELS.visits, locale) : t(LABELS.count, locale),
        },
      }
    }
    case 'bar': {
      return {
        ...base,
        type: 'bar',
        data: {
          series: [{ id: 'value', label: element.title, colorIndex: 1 }],
          points: STAFF.map((category) => ({ x: category, value: intBetween(rand, 5, 80) })),
          xLabel: element.title,
          yLabel: t(LABELS.count, locale),
        },
      }
    }
    case 'stacked-bar': {
      return {
        ...base,
        type: 'stacked-bar',
        data: {
          series: [
            { id: 'a', label: element.title, colorIndex: 0 },
            { id: 'b', label: element.title, colorIndex: 2 },
          ],
          points: labels.slice(-7).map((label) => ({
            x: label,
            a: intBetween(rand, 0, 9),
            b: intBetween(rand, 0, 6),
          })),
          xLabel: t(LABELS.day, locale),
          yLabel: t(LABELS.count, locale),
        },
      }
    }
    case 'donut': {
      const slices = [
        { id: 'a', label: t(LABELS.indoor, locale) },
        { id: 'b', label: t(LABELS.outdoor, locale) },
      ].map((slice, index) => ({ ...slice, value: intBetween(rand, 8, 90), colorIndex: index }))
      const total = slices.reduce((sum, slice) => sum + slice.value, 0)
      return {
        ...base,
        type: 'donut',
        data: { slices, centerLabel: t(LABELS.total, locale), centerValue: String(total) },
      }
    }
    case 'heatmap': {
      return {
        ...base,
        type: 'heatmap',
        data: {
          xLabels: HOURS,
          yLabels: DAYS.map((day) => t(day, locale)),
          cells: DAYS.map(() => HOURS.map(() => intBetween(rand, 0, 60))),
          unit: t(LABELS.people, locale),
        },
      }
    }
    case 'alert': {
      const severity = severityFor(rand)
      return {
        ...base,
        type: 'alert',
        data: {
          severity,
          headline: t(
            severity === 'ok' ? LABELS.noAlert : severity === 'warn' ? LABELS.approaching : LABELS.activeNow,
            locale,
          ),
          detail: element.description,
          meta:
            severity === 'ok'
              ? t(LABELS.lastFlagged, locale)
              : `${t(LABELS.since, locale)} ${intBetween(rand, 10, 18)}:${String(intBetween(rand, 10, 59))}`,
        },
      }
    }
    case 'table':
      return { ...base, type: 'table', data: tablePayload(id, rand, locale) }
    case 'camera-grid': {
      return {
        ...base,
        type: 'camera-grid',
        data: {
          feeds: CAMERA_COVERAGE.map(([camera, zone]) => {
            const online = rand() > 0.12
            return {
              id: camera,
              label: `${t(LABELS.camera, locale)} ${camera}`,
              zone: t(zone, locale),
              status: online ? ('online' as const) : ('offline' as const),
              statusLabel: t(online ? LABELS.online : LABELS.offline, locale),
              // The real backend returns an HLS/WebRTC URL here.
              streamUrl: online ? `/api/cameras/${camera}/stream.m3u8` : undefined,
            }
          }),
        },
      }
    }
  }
}

/**
 * The 30-day history behind a monitor, used by the alert builder so the user
 * can see what "normal" looks like before picking a threshold.
 */
export function monthlyTrend(id: string, seedKey: string, locale: Locale) {
  const element = findElement(id, locale)
  const rand = makeRandom(`${id}|${seedKey}`)
  const labels = Array.from({ length: 30 }, (_, i) => `${t(LABELS.day30, locale)}${29 - i}`)
  const points = trendPoints(rand, labels, 'value', isDuration(id) ? 1 : 0, isDuration(id) ? 14 : 60)
  const total = points.reduce((sum, point) => sum + Number(point.value ?? 0), 0)
  const average = Math.round(total / (points.length || 1))
  return {
    points,
    average,
    averageLabel: isDuration(id) ? duration(average, 0, locale) : String(average),
    series: { id: 'value', label: element?.title ?? id, colorIndex: 0 },
  }
}

export function buildInstanceLog(id: string, seedKey: string, locale: Locale): InstanceLog {
  const element = findElement(id, locale)
  const rand = makeRandom(`instances|${id}|${seedKey}`)
  const total = intBetween(rand, 3, 12)
  const cameras = element?.cameras?.length ? element.cameras : ['03']
  const instances: Instance[] = Array.from({ length: total }, (_, index) => ({
    id: `${id}-${index}`,
    timestamp: `${String(intBetween(rand, 8, 21)).padStart(2, '0')}:${String(intBetween(rand, 0, 59)).padStart(2, '0')}`,
    camera: `${t(LABELS.camera, locale)} ${cameras[index % cameras.length]}`,
    detail: element?.description,
    severity: severityFor(rand),
    clipUrl: `/api/clips/${id}/${index}.mp4`,
  }))
  return { elementId: id, title: element?.title ?? id, total, instances }
}
