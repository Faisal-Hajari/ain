import type { DashboardConfig, ElementDef, Locale, SectionDef, SectionView } from '@/api/types'

/**
 * Stand-in for `GET /api/dashboard/config`. Elements are declared once in a
 * registry and referenced by id from the sections, so the same KPI can appear
 * on Overview and on its own tab without drifting - and both share one cache
 * entry, so the two tabs always agree.
 *
 * Text is held per locale because the real backend is what localises the
 * dashboard; the frontend only asks for a language.
 */

type Text = Record<Locale, string>

interface ElementSpec extends Omit<ElementDef, 'title' | 'description'> {
  title: Text
  description: Text
}

interface SectionSpec {
  id: string
  title: Text
  description: Text
  view?: SectionView
  /** Element ids, with an optional per-section span override. */
  items: { ref: string; span?: ElementDef['span'] }[]
}

const ELEMENTS: ElementSpec[] = [
  {
    id: 'live-occupancy',
    title: { en: 'Live occupancy', ar: 'الإشغال الحالي' },
    description: {
      en: 'Headcount currently on-site, split indoor and outdoor.',
      ar: 'عدد الأشخاص الموجودين حالياً في الموقع، داخلياً وخارجياً.',
    },
    type: 'stat-group',
    kind: 'monitor',
    updates: 'realtime',
    span: 2,
    cameras: ['03', '04', '06', '07', '10'],
  },
  {
    id: 'footfall',
    title: { en: 'Footfall', ar: 'حركة الدخول' },
    description: { en: 'People crossing the entrance per hour.', ar: 'عدد الأشخاص العابرين للمدخل في الساعة.' },
    type: 'line',
    kind: 'monitor',
    updates: 'hourly',
    span: 2,
    cameras: ['03'],
  },
  {
    id: 'dwell-time-per-table',
    title: { en: 'Dwell time per table', ar: 'مدة الجلوس لكل طاولة' },
    description: { en: 'Minutes from seating to vacate.', ar: 'الدقائق من الجلوس حتى مغادرة الطاولة.' },
    type: 'histogram',
    kind: 'monitor',
    updates: 'visit',
    span: 2,
    cameras: ['03', '04'],
  },
  {
    id: 'queue-length',
    title: { en: 'Queue length', ar: 'طول الطابور' },
    description: { en: 'Customers waiting at the counter.', ar: 'عدد العملاء المنتظرين عند الكاونتر.' },
    type: 'kpi',
    kind: 'monitor',
    updates: 'realtime',
    cameras: ['03', '11'],
  },
  {
    id: 'queue-wait-time',
    title: { en: 'Queue wait time', ar: 'زمن الانتظار في الطابور' },
    description: {
      en: 'Time customers spent in queue.',
      ar: 'الوقت الذي يقضيه العملاء في الطابور.',
    },
    type: 'kpi',
    kind: 'monitor',
    updates: 'event',
    cameras: ['03', '11'],
  },
  {
    id: 'congestion-count',
    title: { en: 'Congestion count', ar: 'عدد حالات الازدحام' },
    description: {
      en: 'Times occupancy passed 90% with a growing queue.',
      ar: 'عدد المرات التي تجاوز فيها الإشغال ٩٠٪ مع تزايد الطابور.',
    },
    type: 'kpi',
    kind: 'alert',
    updates: 'event',
    drilldown: 'instances',
    cameras: ['03', '04'],
  },
  {
    id: 'empty-restaurant-count',
    title: { en: 'Empty-restaurant count', ar: 'عدد حالات خلو المطعم' },
    description: {
      en: 'Times traffic stayed below average for more than X minutes.',
      ar: 'عدد المرات التي بقيت فيها الحركة دون المعدل لأكثر من X دقيقة.',
    },
    type: 'kpi',
    kind: 'alert',
    updates: 'event',
    drilldown: 'instances',
    cameras: ['03', '04'],
  },
  {
    id: 'long-wait-count',
    title: { en: 'Long-wait count', ar: 'عدد حالات الانتظار الطويل' },
    description: {
      en: 'Times a customer waited beyond X minutes.',
      ar: 'عدد المرات التي انتظر فيها عميل أكثر من X دقيقة.',
    },
    type: 'kpi',
    kind: 'alert',
    updates: 'event',
    drilldown: 'instances',
    cameras: ['03', '11'],
  },
  {
    id: 'no-gloves-count',
    title: { en: 'No-gloves count', ar: 'عدد حالات عدم ارتداء القفازات' },
    description: {
      en: 'Times staff prepped without required gloves.',
      ar: 'عدد المرات التي حضّر فيها الموظف دون القفازات المطلوبة.',
    },
    type: 'kpi',
    kind: 'alert',
    updates: 'event',
    drilldown: 'instances',
    cameras: ['05'],
  },
  {
    id: 'no-hair-cover-count',
    title: { en: 'No-hair-cover count', ar: 'عدد حالات عدم تغطية الشعر' },
    description: {
      en: 'Times a hairnet or cap was missing at prep.',
      ar: 'عدد المرات التي غابت فيها شبكة الشعر أو القبعة أثناء التحضير.',
    },
    type: 'kpi',
    kind: 'alert',
    updates: 'event',
    drilldown: 'instances',
    cameras: ['05'],
  },
  {
    id: 'no-mask-count',
    title: { en: 'No-mask count', ar: 'عدد حالات عدم ارتداء الكمامة' },
    description: {
      en: 'Times a mask was absent or worn incorrectly.',
      ar: 'عدد المرات التي غابت فيها الكمامة أو ارتُديت بشكل غير صحيح.',
    },
    type: 'kpi',
    kind: 'alert',
    updates: 'event',
    drilldown: 'instances',
    cameras: ['05'],
  },
  {
    id: 'camera-status',
    title: { en: 'Feed health', ar: 'حالة البث' },
    description: { en: 'Cameras reporting frames right now.', ar: 'الكاميرات التي ترسل بثاً في الوقت الحالي.' },
    type: 'stat-group',
    kind: 'monitor',
    updates: 'realtime',
    span: 2,
  },
  {
    id: 'camera-feeds',
    title: { en: 'Camera feeds', ar: 'بث الكاميرات' },
    description: {
      en: 'Every camera installed at the branch and the zone it covers.',
      ar: 'كل كاميرا مركّبة في الفرع والمنطقة التي تغطيها.',
    },
    type: 'camera-grid',
    kind: 'monitor',
    updates: 'realtime',
    span: 4,
  },
]

const ALERT_ELEMENTS = ELEMENTS.filter((element) => element.kind === 'alert').map((element) => ({
  ref: element.id,
}))

const sectionSpecs: SectionSpec[] = [
  {
    id: 'overview',
    title: { en: 'Overview', ar: 'نظرة عامة' },
    description: { en: 'A quick look across the branch.', ar: 'نظرة سريعة على الفرع.' },
    items: [
      { ref: 'live-occupancy' },
      { ref: 'queue-length' },
      { ref: 'queue-wait-time' },
      { ref: 'footfall' },
      { ref: 'congestion-count' },
      { ref: 'long-wait-count' },
    ],
  },
  {
    id: 'customer',
    title: { en: 'Customer intelligence', ar: 'ذكاء العملاء' },
    description: { en: 'Information about the customers.', ar: 'معلومات عن العملاء.' },
    items: [
      { ref: 'live-occupancy' },
      { ref: 'footfall' },
      { ref: 'queue-length' },
      { ref: 'queue-wait-time' },
      { ref: 'dwell-time-per-table' },
      { ref: 'congestion-count' },
      { ref: 'empty-restaurant-count' },
      { ref: 'long-wait-count' },
    ],
  },
  {
    id: 'employees',
    title: { en: 'Employee monitoring', ar: 'مراقبة الموظفين' },
    description: { en: 'Information about the employees.', ar: 'معلومات عن الموظفين.' },
    items: [{ ref: 'no-gloves-count' }, { ref: 'no-hair-cover-count' }, { ref: 'no-mask-count' }],
  },
  {
    id: 'cameras',
    title: { en: 'Cameras', ar: 'الكاميرات' },
    description: { en: 'Cameras and camera feeds.', ar: 'الكاميرات وبثّها المباشر.' },
    items: [{ ref: 'camera-status' }, { ref: 'camera-feeds' }],
  },
  {
    id: 'alerts',
    title: { en: 'Alerts', ar: 'التنبيهات' },
    description: {
      en: 'Every alert count, and the rules that raise them.',
      ar: 'كل عدادات التنبيهات، والقواعد التي تطلقها.',
    },
    view: 'alerts',
    items: ALERT_ELEMENTS,
  },
]

const filterSpecs = [
  {
    id: 'branch',
    label: { en: 'Branch', ar: 'الفرع' },
    defaultValue: 'olaya',
    options: [
      { value: 'olaya', label: { en: 'Riyadh - Olaya', ar: 'الرياض - العليا' } },
      { value: 'malaz', label: { en: 'Riyadh - Malaz', ar: 'الرياض - الملز' } },
      { value: 'all', label: { en: 'All branches', ar: 'كل الفروع' } },
    ],
  },
  {
    id: 'venue',
    label: { en: 'Venue type', ar: 'نوع المنشأة' },
    defaultValue: 'cafe',
    options: [
      { value: 'cafe', label: { en: 'Cafe', ar: 'مقهى' } },
      { value: 'kitchen', label: { en: 'Kitchen', ar: 'مطبخ' } },
      { value: 'fnb', label: { en: 'F&B', ar: 'أغذية ومشروبات' } },
      { value: 'drive-thru', label: { en: 'Drive-thru', ar: 'خدمة السيارات' } },
      { value: 'all', label: { en: 'All venue types', ar: 'كل الأنواع' } },
    ],
  },
  {
    id: 'range',
    label: { en: 'Date range', ar: 'النطاق الزمني' },
    control: 'date-range' as const,
    defaultValue: 'today',
    options: [
      { value: 'today', label: { en: 'Today', ar: 'اليوم' } },
      { value: '7d', label: { en: 'Last 7 days', ar: 'آخر ٧ أيام' } },
      { value: '30d', label: { en: 'Last 30 days', ar: 'آخر ٣٠ يوماً' } },
    ],
  },
]

const BRANCH_LABEL: Text = { en: 'Riyadh - Olaya', ar: 'الرياض - العليا' }

function toElement(spec: ElementSpec, locale: Locale, span?: ElementDef['span']): ElementDef {
  const { title, description, ...rest } = spec
  return { ...rest, span: span ?? rest.span, title: title[locale], description: description[locale] }
}

function specById(id: string): ElementSpec | undefined {
  return ELEMENTS.find((element) => element.id === id)
}

export function buildConfig(locale: Locale): DashboardConfig {
  const sections: SectionDef[] = sectionSpecs.map((section) => ({
    id: section.id,
    title: section.title[locale],
    description: section.description[locale],
    view: section.view,
    elements: section.items.flatMap((item) => {
      const spec = specById(item.ref)
      return spec ? [toElement(spec, locale, item.span)] : []
    }),
  }))

  return {
    branchLabel: BRANCH_LABEL[locale],
    today: new Date().toISOString().slice(0, 10),
    filters: filterSpecs.map((filter) => ({
      id: filter.id,
      label: filter.label[locale],
      control: 'control' in filter ? filter.control : undefined,
      defaultValue: filter.defaultValue,
      options: filter.options.map((option) => ({ value: option.value, label: option.label[locale] })),
    })),
    sections,
  }
}

/** Element lookup for the payload endpoints, already localised. */
export function findElement(id: string, locale: Locale): ElementDef | undefined {
  const spec = specById(id)
  return spec ? toElement(spec, locale) : undefined
}

/** Every monitor an alert rule can be built on. */
export function monitorElements(locale: Locale): ElementDef[] {
  return ELEMENTS.filter((element) => element.kind === 'monitor' && element.type !== 'camera-grid').map((element) =>
    toElement(element, locale),
  )
}
