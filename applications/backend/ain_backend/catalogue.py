"""The layout the backend owns: cameras, filters, elements, sections.

Elements are declared once and referenced by id from the sections, so
the same card can sit on Overview and on its own tab without drifting -
and the frontend, which caches by id, can never show two of them
disagreeing.
"""

import dataclasses
import datetime
import zoneinfo

from ain_backend import formatting
from ain_backend import i18n
from ain_backend import models

# Every date and pre-formatted timestamp is branch-local, and `today`
# comes from here rather than from the viewer's clock.
BRANCH_TIMEZONE = zoneinfo.ZoneInfo('Asia/Riyadh')
BRANCH_LABEL = i18n.Text('Riyadh - Olaya', 'الرياض - العليا')

_ValueFormat = formatting.ValueFormat
_Type = models.ElementType
_Kind = models.ElementKind
_Cadence = models.UpdateCadence


def now() -> datetime.datetime:
	"""Returns the current branch-local time."""
	return datetime.datetime.now(BRANCH_TIMEZONE)


def today() -> datetime.date:
	"""Returns the branch's current date."""
	return now().date()


@dataclasses.dataclass(frozen=True)
class CameraSpec:
	"""A CCTV feed as installed at the branch."""

	id: str
	zone: i18n.Text

	@property
	def stream_url(self) -> str:
		"""Where a browser plays this camera.

		Returns:
			The camera's HLS playlist. The dashboard's own origin
			proxies this path straight through - nginx in the frontend
			image, the dev-server proxy under vite - so the tile plays a
			same-origin URL and no hostname is baked into a payload.
			The path is the id without its leading zero, which is what
			the recordings are named.
		"""
		return f'/cam{int(self.id)}/index.m3u8'


@dataclasses.dataclass(frozen=True)
class ElementSpec:
	"""One card, before it is localised into an `ElementDef`."""

	id: str
	title: i18n.Text
	description: i18n.Text
	type: models.ElementType
	kind: models.ElementKind
	updates: models.UpdateCadence
	span: int = 1
	cameras: tuple[str, ...] = ()
	drilldown: str | None = None
	value_format: formatting.ValueFormat = _ValueFormat.COUNT
	unit: i18n.Text | None = None
	# The band the dummy generator varies within, in the element's own
	# units - minutes for durations, percent for gauges.
	value_min: float = 0
	value_max: float = 24


@dataclasses.dataclass(frozen=True)
class SectionSpec:
	"""One nav tab, referring to elements by id."""

	id: str
	title: i18n.Text
	description: i18n.Text
	element_ids: tuple[str, ...]
	view: str | None = None


CAMERAS: tuple[CameraSpec, ...] = (
	CameraSpec('03', i18n.Text(
		'Indoor entrance and lobby / waiting area.',
		'المدخل الداخلي والبهو / منطقة الانتظار.',
	)),
	CameraSpec('04', i18n.Text(
		'Indoor seating area (high-top tables).',
		'منطقة الجلوس الداخلية (طاولات مرتفعة).',
	)),
	CameraSpec('05', i18n.Text(
		'Back-of-house kitchen - fryer line and hot-food prep.',
		'مطبخ المؤخرة - خط القلي وتحضير الطعام الساخن.',
	)),
	CameraSpec('06', i18n.Text(
		'Outdoor street frontage and parking bays.',
		'واجهة الشارع ومواقف السيارات.',
	)),
	CameraSpec('09', i18n.Text(
		'Outdoor parking area and street frontage.',
		'منطقة المواقف الخارجية وواجهة الشارع.',
	)),
	CameraSpec('10', i18n.Text(
		'Outdoor rear / side parking and lane.',
		'المواقف الخلفية / الجانبية والممر.',
	)),
	CameraSpec('11', i18n.Text(
		'Register / POS and cashier station.',
		'الصندوق ونقطة البيع ومحطة الكاشير.',
	)),
	CameraSpec('12', i18n.Text(
		'Service counter and hot-food display.',
		'كاونتر الخدمة وعرض الطعام الساخن.',
	)),
	CameraSpec('13', i18n.Text(
		'Back-of-house storage and utility corridor.',
		'مخزن المؤخرة وممر الخدمات.',
	)),
	CameraSpec('15', i18n.Text(
		'Rear service alley and delivery / back door.',
		'ممر الخدمة الخلفي وباب التوصيل.',
	)),
)

CAMERAS_BY_ID = {camera.id: camera for camera in CAMERAS}

ELEMENTS: tuple[ElementSpec, ...] = (
	ElementSpec(
		id='live-occupancy',
		title=i18n.Text('Live occupancy', 'الإشغال الحالي'),
		description=i18n.Text(
			'Headcount currently on-site, split indoor and outdoor.',
			'عدد الأشخاص الموجودين حالياً في الموقع، داخلياً وخارجياً.',
		),
		type=_Type.STAT_GROUP, kind=_Kind.MONITOR,
		updates=_Cadence.REALTIME, span=2,
		cameras=('03', '04', '06', '09', '10'),
		unit=i18n.PEOPLE,
		value_min=8, value_max=60,
	),
	ElementSpec(
		id='footfall',
		title=i18n.Text('Footfall', 'حركة الدخول'),
		description=i18n.Text(
			'People crossing the entrance per hour.',
			'عدد الأشخاص العابرين للمدخل في الساعة.',
		),
		type=_Type.LINE, kind=_Kind.MONITOR, updates=_Cadence.HOURLY,
		span=2, cameras=('03',), unit=i18n.PEOPLE,
		value_min=4, value_max=140,
	),
	ElementSpec(
		id='queue-length',
		title=i18n.Text('Queue length', 'طول الطابور'),
		description=i18n.Text(
			'Customers waiting at the counter.',
			'عدد العملاء المنتظرين عند الكاونتر.',
		),
		type=_Type.KPI, kind=_Kind.MONITOR, updates=_Cadence.REALTIME,
		cameras=('03', '11'),
		unit=i18n.PEOPLE,
		value_min=0, value_max=18,
	),
	ElementSpec(
		id='queue-wait-time',
		title=i18n.Text('Queue wait time', 'زمن الانتظار في الطابور'),
		description=i18n.Text(
			'Time customers spent in queue.',
			'الوقت الذي يقضيه العملاء في الطابور.',
		),
		type=_Type.KPI, kind=_Kind.MONITOR, updates=_Cadence.EVENT,
		cameras=('03', '11'),
		value_format=_ValueFormat.DURATION,
		value_min=1, value_max=14,
	),
	ElementSpec(
		id='dwell-time-per-table',
		title=i18n.Text('Dwell time per table', 'مدة الجلوس لكل طاولة'),
		description=i18n.Text(
			'Minutes from seating to vacate.',
			'الدقائق من الجلوس حتى مغادرة الطاولة.',
		),
		type=_Type.HISTOGRAM, kind=_Kind.MONITOR, updates=_Cadence.VISIT,
		span=2, cameras=('03', '04'),
		value_min=4, value_max=90,
	),
	ElementSpec(
		id='congestion-count',
		title=i18n.Text('Congestion count', 'عدد حالات الازدحام'),
		description=i18n.Text(
			'Times occupancy passed 90% with a growing queue.',
			'عدد المرات التي تجاوز فيها الإشغال ٩٠٪ مع تزايد الطابور.',
		),
		type=_Type.KPI, kind=_Kind.ALERT, updates=_Cadence.EVENT,
		cameras=('03', '04'), drilldown='instances', unit=i18n.EVENTS,
		value_min=0, value_max=14,
	),
	ElementSpec(
		id='empty-restaurant-count',
		title=i18n.Text('Empty-restaurant count', 'عدد حالات خلو المطعم'),
		description=i18n.Text(
			'Times traffic stayed below average for more than X minutes.',
			'عدد المرات التي بقيت فيها الحركة دون المعدل لأكثر من X دقيقة.',
		),
		type=_Type.KPI, kind=_Kind.ALERT, updates=_Cadence.EVENT,
		cameras=('03', '04'), drilldown='instances', unit=i18n.EVENTS,
		value_min=0, value_max=8,
	),
	ElementSpec(
		id='long-wait-count',
		title=i18n.Text('Long-wait count', 'عدد حالات الانتظار الطويل'),
		description=i18n.Text(
			'Times a customer waited beyond X minutes.',
			'عدد المرات التي انتظر فيها عميل أكثر من X دقيقة.',
		),
		type=_Type.KPI, kind=_Kind.ALERT, updates=_Cadence.EVENT,
		cameras=('03', '11'), drilldown='instances', unit=i18n.EVENTS,
		value_min=0, value_max=16,
	),
	ElementSpec(
		id='no-gloves-count',
		title=i18n.Text('No-gloves count', 'عدد حالات عدم ارتداء القفازات'),
		description=i18n.Text(
			'Times staff prepped without required gloves.',
			'عدد المرات التي حضّر فيها الموظف دون القفازات المطلوبة.',
		),
		type=_Type.KPI, kind=_Kind.ALERT, updates=_Cadence.EVENT,
		cameras=('05',), drilldown='instances', unit=i18n.EVENTS,
		value_min=0, value_max=14,
	),
	ElementSpec(
		id='no-hair-cover-count',
		title=i18n.Text('No-hair-cover count', 'عدد حالات عدم تغطية الشعر'),
		description=i18n.Text(
			'Times a hairnet or cap was missing at prep.',
			'عدد المرات التي غابت فيها شبكة الشعر أو القبعة أثناء التحضير.',
		),
		type=_Type.KPI, kind=_Kind.ALERT, updates=_Cadence.EVENT,
		cameras=('05',), drilldown='instances', unit=i18n.EVENTS,
		value_min=0, value_max=12,
	),
	ElementSpec(
		id='no-mask-count',
		title=i18n.Text('No-mask count', 'عدد حالات عدم ارتداء الكمامة'),
		description=i18n.Text(
			'Times a mask was absent or worn incorrectly.',
			'عدد المرات التي غابت فيها الكمامة أو ارتُديت بشكل غير صحيح.',
		),
		type=_Type.KPI, kind=_Kind.ALERT, updates=_Cadence.EVENT,
		cameras=('05',), drilldown='instances', unit=i18n.EVENTS,
		value_min=0, value_max=16,
	),
	ElementSpec(
		id='camera-status',
		title=i18n.Text('Feed health', 'حالة البث'),
		description=i18n.Text(
			'Cameras reporting frames now, and how many were down.',
			'الكاميرات التي ترسل بثاً الآن، وعدد ما توقف منها.',
		),
		type=_Type.STAT_GROUP, kind=_Kind.MONITOR,
		updates=_Cadence.REALTIME, span=4,
	),
	ElementSpec(
		id='camera-feeds',
		title=i18n.Text('Camera feeds', 'بث الكاميرات'),
		description=i18n.Text(
			'Every camera installed at the branch and the zone it covers.',
			'كل كاميرا مركّبة في الفرع والمنطقة التي تغطيها.',
		),
		type=_Type.CAMERA_GRID, kind=_Kind.MONITOR,
		updates=_Cadence.REALTIME, span=4,
	),
)

ELEMENTS_BY_ID = {element.id: element for element in ELEMENTS}

_ALERT_ELEMENT_IDS = tuple(
	element.id
	for element in ELEMENTS
	if element.kind is _Kind.ALERT
)

SECTIONS: tuple[SectionSpec, ...] = (
	SectionSpec(
		id='overview',
		title=i18n.Text('Overview', 'نظرة عامة'),
		description=i18n.Text(
			'A quick look across the branch.', 'نظرة سريعة على الفرع.'
		),
		element_ids=(
			'live-occupancy',
			'queue-length',
			'queue-wait-time',
			'footfall',
			'congestion-count',
			'long-wait-count',
		),
	),
	SectionSpec(
		id='customer',
		title=i18n.Text('Customer intelligence', 'ذكاء العملاء'),
		description=i18n.Text(
			'Information about the customers.', 'معلومات عن العملاء.'
		),
		element_ids=(
			'live-occupancy',
			'footfall',
			'queue-length',
			'queue-wait-time',
			'dwell-time-per-table',
			'congestion-count',
			'empty-restaurant-count',
			'long-wait-count',
		),
	),
	SectionSpec(
		id='employees',
		title=i18n.Text('Employee monitoring', 'مراقبة الموظفين'),
		description=i18n.Text(
			'Information about the employees.', 'معلومات عن الموظفين.'
		),
		element_ids=(
			'no-gloves-count',
			'no-hair-cover-count',
			'no-mask-count',
		),
	),
	SectionSpec(
		id='cameras',
		title=i18n.Text('Cameras', 'الكاميرات'),
		description=i18n.Text(
			'Cameras and camera feeds.', 'الكاميرات وبثّها المباشر.'
		),
		element_ids=('camera-status', 'camera-feeds'),
	),
	SectionSpec(
		id='alerts',
		title=i18n.Text('Alerts', 'التنبيهات'),
		description=i18n.Text(
			'Every alert count, and the rules that raise them.',
			'كل عدادات التنبيهات، والقواعد التي تطلقها.',
		),
		element_ids=_ALERT_ELEMENT_IDS,
		view='alerts',
	),
)


@dataclasses.dataclass(frozen=True)
class FilterSpec:
	"""A global control, before it is localised."""

	id: str
	label: i18n.Text
	default_value: str
	options: tuple[tuple[str, i18n.Text], ...]
	control: str | None = None


FILTERS: tuple[FilterSpec, ...] = (
	FilterSpec(
		id='branch',
		label=i18n.Text('Branch', 'الفرع'),
		default_value='olaya',
		options=(
			('olaya', i18n.Text('Riyadh - Olaya', 'الرياض - العليا')),
			('malaz', i18n.Text('Riyadh - Malaz', 'الرياض - الملز')),
			('all', i18n.Text('All branches', 'كل الفروع')),
		),
	),
	FilterSpec(
		id='venue',
		label=i18n.Text('Venue type', 'نوع المنشأة'),
		default_value='cafe',
		options=(
			('cafe', i18n.Text('Cafe', 'مقهى')),
			('kitchen', i18n.Text('Kitchen', 'مطبخ')),
			('fnb', i18n.Text('F&B', 'أغذية ومشروبات')),
			('drive-thru', i18n.Text('Drive-thru', 'خدمة السيارات')),
			('all', i18n.Text('All venue types', 'كل الأنواع')),
		),
	),
	FilterSpec(
		id='range',
		label=i18n.Text('Date range', 'النطاق الزمني'),
		default_value='today',
		control='date-range',
		options=(
			('today', i18n.Text('Today', 'اليوم')),
			('7d', i18n.Text('Last 7 days', 'آخر ٧ أيام')),
			('30d', i18n.Text('Last 30 days', 'آخر ٣٠ يوماً')),
		),
	),
)


def element_def(
	spec: ElementSpec, locale: i18n.Locale
) -> models.ElementDef:
	"""Localises one element spec for the wire."""
	return models.ElementDef(
		id=spec.id,
		title=spec.title.get(locale),
		description=spec.description.get(locale),
		type=spec.type,
		kind=spec.kind,
		updates=spec.updates,
		span=spec.span,
		cameras=list(spec.cameras) or None,
		drilldown=spec.drilldown,
	)


def build_config(locale: i18n.Locale) -> models.DashboardConfig:
	"""Builds the whole layout in one language.

	Args:
		locale: The requested language.

	Returns:
		The navigation, filters and card layout the frontend renders.
	"""
	sections = [
		models.SectionDef(
			id=section.id,
			title=section.title.get(locale),
			description=section.description.get(locale),
			view=section.view,
			elements=[
				element_def(ELEMENTS_BY_ID[element_id], locale)
				for element_id in section.element_ids
				if element_id in ELEMENTS_BY_ID
			],
		)
		for section in SECTIONS
	]
	filters = [
		models.FilterDef(
			id=spec.id,
			label=spec.label.get(locale),
			control=spec.control,
			default_value=spec.default_value,
			options=[
				models.FilterOption(value=value, label=label.get(locale))
				for value, label in spec.options
			],
		)
		for spec in FILTERS
	]
	return models.DashboardConfig(
		branch_label=BRANCH_LABEL.get(locale),
		today=today().isoformat(),
		filters=filters,
		sections=sections,
	)


def monitor_elements() -> list[ElementSpec]:
	"""Returns the elements an alert rule can be built on.

	Returns:
		Every monitor carrying a numeric value - which excludes the
		camera grid.
	"""
	numeric = (
		_Type.KPI, _Type.STAT_GROUP, _Type.LINE, _Type.HISTOGRAM,
	)
	return [
		element
		for element in ELEMENTS
		if element.kind is _Kind.MONITOR and element.type in numeric
	]
