"""The static KPI and element catalogue for a single branch.

Nothing here is computed: it is the transcription of the catalogue the
dashboard is built against. Values for these elements come from
`ain_backend.dummy` until the real read models exist.
"""

from ain_backend import models

CAMERAS: list[models.Camera] = [
	models.Camera(
		id='03',
		label='Camera 03',
		coverage=(
			'Indoor entrance and lobby / waiting area (bench seating), '
			'with a sightline through the glass doors to the street.'
		),
		placement=models.Placement.INDOOR,
	),
	models.Camera(
		id='04',
		label='Camera 04',
		coverage=(
			'Indoor seating area (high-top tables), with a window line '
			'of sight to the street.'
		),
		placement=models.Placement.INDOOR,
	),
	models.Camera(
		id='05',
		label='Camera 05',
		coverage='Back-of-house kitchen - fryer line and hot-food prep.',
		placement=models.Placement.BACK_OF_HOUSE,
	),
	models.Camera(
		id='06',
		label='Camera 06',
		coverage=(
			'Outdoor street frontage and parking bays (night coverage).'
		),
		placement=models.Placement.OUTDOOR,
	),
	models.Camera(
		id='07',
		label='Camera 07',
		coverage='Outdoor parking area and street frontage.',
		placement=models.Placement.OUTDOOR,
	),
	models.Camera(
		id='10',
		label='Camera 10',
		coverage=(
			'Outdoor rear / side parking and lane (night coverage).'
		),
		placement=models.Placement.OUTDOOR,
	),
	models.Camera(
		id='11',
		label='Camera 11',
		coverage='Register / POS and cashier station.',
		placement=models.Placement.INDOOR,
	),
	models.Camera(
		id='12',
		label='Camera 12',
		coverage=(
			'Service counter and hot-food display, hallway leading to '
			'the counter.'
		),
		placement=models.Placement.INDOOR,
	),
	models.Camera(
		id='13',
		label='Camera 13',
		coverage=(
			'Back-of-house storage and utility corridor (walk-in '
			'coolers, mop station).'
		),
		placement=models.Placement.BACK_OF_HOUSE,
	),
	models.Camera(
		id='15',
		label='Camera 15',
		coverage='Rear service alley and delivery / back door.',
		placement=models.Placement.BACK_OF_HOUSE,
	),
]

FILTERS = models.FilterCatalogue(
	branches=[
		models.FilterOption(
			id='riyadh-01', label='Riyadh 01', label_ar='01 الرياض'
		),
	],
	venue_types=[
		models.FilterOption(id='cafe', label='Cafe', label_ar='مقهى'),
		models.FilterOption(id='kitchen', label='Kitchen', label_ar='مطبخ'),
		models.FilterOption(id='fnb', label='F&B', label_ar='أغذية ومشروبات'),
		models.FilterOption(
			id='drive-thru', label='Drive-thru', label_ar='خدمة السيارات'
		),
	],
	date_ranges=[
		models.FilterOption(id='today', label='Today', label_ar='اليوم'),
		models.FilterOption(id='yesterday', label='Yesterday', label_ar='أمس'),
		models.FilterOption(id='7d', label='7 days', label_ar='٧ أيام'),
		models.FilterOption(id='30d', label='30 days', label_ar='٣٠ يوماً'),
		models.FilterOption(id='custom', label='Custom', label_ar='مخصص'),
	],
	languages=[
		models.FilterOption(id='en', label='English', label_ar='الإنجليزية'),
		models.FilterOption(id='ar', label='Arabic', label_ar='العربية'),
	],
)

_SECTION_META: list[tuple[str, str, str]] = [
	(
		'customer-intelligence',
		'Customer intelligence & footfall',
		'Who comes in, how many are on-site, and how they are seated.',
	),
	(
		'service-queue',
		'Service & queue',
		'How long guests wait and how quickly the counter clears them.',
	),
	(
		'kitchen-operations',
		'Kitchen operations',
		'Back-of-house throughput. No elements defined in the catalogue '
		'yet - the section is served so the front end can reserve it.',
	),
	(
		'hygiene-compliance',
		'Hygiene & compliance',
		'Measured hygiene violations. Live pass/fail detections are '
		'states, not metrics, so they surface as staff-conduct alerts.',
	),
	(
		'employee-monitoring',
		'Employee monitoring',
		'Attendance derived from the entrance and counter feeds, plus '
		'per-employee productivity and PPE adherence.',
	),
	(
		'staff-conduct',
		'Staff conduct alerts',
		'General-conduct flags that affect service or professionalism '
		'without being a hygiene or safety violation on their own.',
	),
]


def _element(
	element_id: str,
	section_id: str,
	name: str,
	measures: str,
	types: list[models.ElementType],
	cadence: models.Cadence,
	cameras: list[str],
	value_kind: models.ValueKind,
	unit: str,
	baseline: float,
	has_instances: bool = False,
) -> models.Element:
	"""Builds one catalogue element.

	Args:
		element_id: URL-safe identifier used by every data endpoint.
		section_id: Section the element is listed under.
		name: Display name.
		measures: The catalogue's "what it measures" text.
		types: Render types the front end may draw.
		cadence: Upstream refresh rate.
		cameras: Camera ids the element is derived from.
		value_kind: Which payload shape the data endpoint returns.
		unit: Unit of the headline value.
		baseline: Plausible magnitude the dummy generator varies around.
		has_instances: Whether clicking the card opens an instance log.

	Returns:
		The element, ready to be listed in a section.
	"""
	return models.Element(
		id=element_id,
		section_id=section_id,
		name=name,
		measures=measures,
		types=types,
		cadence=cadence,
		cameras=cameras,
		value_kind=value_kind,
		unit=unit,
		baseline=baseline,
		has_instances=has_instances,
	)


_CARD = models.ElementType.KPI_CARD
_ALERT = models.ElementType.ALERT
_LINE = models.ElementType.GRAPH_LINE
_BAR = models.ElementType.GRAPH_BAR
_DONUT = models.ElementType.GRAPH_DONUT
_HISTOGRAM = models.ElementType.GRAPH_HISTOGRAM
_GAUGE = models.ElementType.GAUGE

_ALERT_COUNT_TYPES = [_CARD, _LINE]

ELEMENTS: list[models.Element] = [
	_element(
		'footfall-entries', 'customer-intelligence', 'Footfall / entries',
		'People crossing the entrance per hour.',
		[_LINE], models.Cadence.HOURLY, ['03'],
		models.ValueKind.COUNT, 'people', 140,
	),
	_element(
		'live-occupancy', 'customer-intelligence', 'Live occupancy',
		'Headcount currently on-site (indoor + outdoor).',
		[_CARD], models.Cadence.REAL_TIME, ['03', '04', '06', '07'],
		models.ValueKind.PEOPLE, 'people', 48,
	),
	_element(
		'live-occupancy-indoor', 'customer-intelligence',
		'Live occupancy (indoor)',
		'Headcount currently on-site, indoor.',
		[_CARD], models.Cadence.REAL_TIME, ['03', '04'],
		models.ValueKind.PEOPLE, 'people', 31,
	),
	_element(
		'live-occupancy-outdoor', 'customer-intelligence',
		'Live occupancy (outdoor)',
		'Headcount currently on-site, outdoor.',
		[_CARD], models.Cadence.REAL_TIME, ['06', '07', '10'],
		models.ValueKind.PEOPLE, 'people', 17,
	),
	_element(
		'table-occupancy-rate', 'customer-intelligence',
		'Table occupancy rate',
		'Share of tables seated versus total.',
		[_GAUGE], models.Cadence.REAL_TIME, ['03', '04'],
		models.ValueKind.PERCENT, 'percent', 72,
	),
	_element(
		'table-utilisation', 'customer-intelligence', 'Table utilisation',
		'Tables filled divided by tables available.',
		[_GAUGE], models.Cadence.REAL_TIME, ['03', '04'],
		models.ValueKind.PERCENT, 'percent', 64,
	),
	_element(
		'dwell-time-per-table', 'customer-intelligence',
		'Dwell time per table',
		'Minutes from seating to vacate.',
		[_HISTOGRAM], models.Cadence.PER_VISIT, ['03', '04'],
		models.ValueKind.DISTRIBUTION, 'visits', 40,
	),
	_element(
		'group-party-size', 'customer-intelligence', 'Group / party size',
		'Distribution of 1s, 2s and 3+.',
		[_BAR], models.Cadence.PER_VISIT, ['03', '04'],
		models.ValueKind.DISTRIBUTION, 'visits', 60,
	),
	_element(
		'demographics-gender', 'customer-intelligence',
		'Demographics (gender)',
		'Aggregate audience profile.',
		[_DONUT], models.Cadence.HOURLY, ['03', '04'],
		models.ValueKind.DISTRIBUTION, 'people', 90,
	),
	_element(
		'congestion-count', 'customer-intelligence', 'Congestion count',
		'Times occupancy passed 90% with a growing queue.',
		_ALERT_COUNT_TYPES, models.Cadence.PER_EVENT, ['03', '04'],
		models.ValueKind.COUNT, 'events', 6, has_instances=True,
	),
	_element(
		'empty-restaurant-count', 'customer-intelligence',
		'Empty-restaurant count',
		'Times traffic stayed below average for more than X min.',
		_ALERT_COUNT_TYPES, models.Cadence.PER_EVENT, ['03', '04'],
		models.ValueKind.COUNT, 'events', 3, has_instances=True,
	),
	_element(
		'queue-length', 'service-queue', 'Queue length',
		'Customers waiting at the counter.',
		[_CARD, _ALERT], models.Cadence.REAL_TIME, ['03', '11'],
		models.ValueKind.PEOPLE, 'people', 7,
	),
	_element(
		'wait-time-to-order', 'service-queue', 'Wait time to order',
		'Seconds from joining queue to served.',
		[_CARD], models.Cadence.PER_EVENT, ['03', '11'],
		models.ValueKind.DURATION, 'seconds', 95,
	),
	_element(
		'counter-service-time', 'service-queue', 'Counter service time',
		'Duration per transaction at the register.',
		[_CARD], models.Cadence.PER_EVENT, ['03', '11'],
		models.ValueKind.DURATION, 'seconds', 138,
	),
	_element(
		'counter-unmanned-time', 'service-queue', 'Counter unmanned time',
		'Whether the till is unmanned - and how long.',
		[_ALERT], models.Cadence.REAL_TIME, ['11'],
		models.ValueKind.DURATION, 'seconds', 240, has_instances=True,
	),
	_element(
		'order-abandonment', 'service-queue', 'Order abandonment',
		'Customers who leave the queue before ordering.',
		[_CARD, _ALERT], models.Cadence.PER_EVENT, ['11'],
		models.ValueKind.COUNT, 'events', 4, has_instances=True,
	),
	_element(
		'table-reset-time', 'service-queue', 'Table reset time',
		'Lag between exit and the table being cleaned.',
		[_CARD, _ALERT], models.Cadence.PER_EVENT, ['03', '04'],
		models.ValueKind.DURATION, 'seconds', 470, has_instances=True,
	),
	_element(
		'long-wait-count', 'service-queue', 'Long-wait count',
		'Times a customer waited beyond X minutes.',
		_ALERT_COUNT_TYPES, models.Cadence.PER_EVENT, ['03', '11'],
		models.ValueKind.COUNT, 'events', 9, has_instances=True,
	),
	_element(
		'queue-abandonment-count', 'service-queue',
		'Queue-abandonment count',
		'Times a customer left before ordering.',
		_ALERT_COUNT_TYPES, models.Cadence.PER_EVENT, ['11'],
		models.ValueKind.COUNT, 'events', 5, has_instances=True,
	),
	_element(
		'register-unattended-count', 'service-queue',
		'Register-unattended count',
		'Times the till was left unmanned past X minutes.',
		_ALERT_COUNT_TYPES, models.Cadence.PER_EVENT, ['11'],
		models.ValueKind.COUNT, 'events', 3, has_instances=True,
	),
	_element(
		'seating-bottleneck-count', 'service-queue',
		'Seating-bottleneck count',
		'Times guests waited while dirty tables sat empty.',
		_ALERT_COUNT_TYPES, models.Cadence.PER_EVENT, ['03', '04'],
		models.ValueKind.COUNT, 'events', 4, has_instances=True,
	),
	_element(
		'uncleaned-table-count', 'service-queue', 'Uncleaned table count',
		'Times a table remained uncleaned for X minutes.',
		_ALERT_COUNT_TYPES, models.Cadence.PER_EVENT, ['03', '04'],
		models.ValueKind.COUNT, 'events', 6, has_instances=True,
	),
	_element(
		'no-gloves-count', 'hygiene-compliance', 'No-gloves count',
		'Times staff prepped without required gloves.',
		_ALERT_COUNT_TYPES, models.Cadence.PER_EVENT, ['05'],
		models.ValueKind.COUNT, 'events', 7, has_instances=True,
	),
	_element(
		'no-hair-cover-count', 'hygiene-compliance',
		'No-hair-cover count',
		'Times a hairnet or cap was missing at prep.',
		_ALERT_COUNT_TYPES, models.Cadence.PER_EVENT, ['05'],
		models.ValueKind.COUNT, 'events', 5, has_instances=True,
	),
	_element(
		'no-mask-count', 'hygiene-compliance', 'No-mask count',
		'Times a mask was absent or worn incorrectly.',
		_ALERT_COUNT_TYPES, models.Cadence.PER_EVENT, ['05'],
		models.ValueKind.COUNT, 'events', 8, has_instances=True,
	),
	_element(
		'clock-in-first-seen', 'employee-monitoring',
		'Clock-in / first-seen',
		'Timestamp a staff member first appears on-site.',
		[_CARD], models.Cadence.PER_EVENT, ['03', '11'],
		models.ValueKind.CLOCK_TIME, 'time', 7.0,
	),
	_element(
		'clock-out-last-seen', 'employee-monitoring',
		'Clock-out / last-seen',
		'Timestamp a staff member is last seen leaving.',
		[_CARD], models.Cadence.PER_EVENT, ['03', '11'],
		models.ValueKind.CLOCK_TIME, 'time', 17.0,
	),
	_element(
		'late-arrival', 'employee-monitoring', 'Late arrival',
		'Arrival after rostered shift start.',
		[_ALERT], models.Cadence.PER_EVENT, ['03', '11'],
		models.ValueKind.COUNT, 'events', 2, has_instances=True,
	),
	_element(
		'early-departure-no-show', 'employee-monitoring',
		'Early departure / no-show',
		'Left before shift end, or absent.',
		[_ALERT], models.Cadence.PER_EVENT, ['03', '11'],
		models.ValueKind.COUNT, 'events', 1, has_instances=True,
	),
	_element(
		'hours-worked', 'employee-monitoring', 'Hours worked',
		'First-seen to last-seen duration per staff.',
		[_CARD], models.Cadence.DAILY, ['03', '11', '05'],
		models.ValueKind.DURATION, 'hours', 8.2,
	),
	_element(
		'break-count-duration', 'employee-monitoring',
		'Break count & duration',
		'Number and length of times away from station.',
		[_CARD, _ALERT], models.Cadence.PER_EVENT, ['05'],
		models.ValueKind.COUNT, 'breaks', 3, has_instances=True,
	),
	_element(
		'throughput-per-employee', 'employee-monitoring',
		'Throughput per employee',
		'Orders handled per staff member.',
		[_BAR], models.Cadence.HOURLY, ['05'],
		models.ValueKind.DISTRIBUTION, 'orders', 34,
	),
	_element(
		'uniform-ppe-adherence', 'employee-monitoring',
		'Uniform / PPE adherence',
		'Per-employee dress and PPE compliance.',
		[_CARD, _ALERT], models.Cadence.REAL_TIME, ['05'],
		models.ValueKind.PERCENT, 'percent', 91,
	),
	_element(
		'no-gloves-count-per-employee', 'employee-monitoring',
		'No-gloves count (per employee)',
		'Times staff prepped without required gloves.',
		[_BAR], models.Cadence.PER_EVENT, ['05'],
		models.ValueKind.DISTRIBUTION, 'events', 7,
	),
	_element(
		'no-hair-cover-count-per-employee', 'employee-monitoring',
		'No-hair-cover count (per employee)',
		'Times a hairnet or cap was missing at prep.',
		[_BAR], models.Cadence.PER_EVENT, ['05'],
		models.ValueKind.DISTRIBUTION, 'events', 5,
	),
	_element(
		'no-mask-count-per-employee', 'employee-monitoring',
		'No-mask count (per employee)',
		'Times a mask was absent or worn incorrectly.',
		[_BAR], models.Cadence.PER_EVENT, ['05'],
		models.ValueKind.DISTRIBUTION, 'events', 8,
	),
	_element(
		'smoking-vaping-count', 'staff-conduct', 'Smoking / vaping count',
		'Times a staff member was seen smoking or vaping on premises.',
		_ALERT_COUNT_TYPES, models.Cadence.PER_EVENT, ['05', '13', '15'],
		models.ValueKind.COUNT, 'events', 2, has_instances=True,
	),
	_element(
		'phone-use-count', 'staff-conduct', 'Phone-use count',
		'Times a staff member used a personal phone while on duty at a '
		'workstation.',
		_ALERT_COUNT_TYPES, models.Cadence.PER_EVENT, ['05', '11', '12'],
		models.ValueKind.COUNT, 'events', 11, has_instances=True,
	),
	_element(
		'off-post-break-count', 'staff-conduct',
		'Off-post / unauthorised break count',
		'Times a staff member left their station outside scheduled '
		'break windows.',
		[_CARD, _ALERT], models.Cadence.PER_EVENT, ['05', '11', '12'],
		models.ValueKind.COUNT, 'events', 4, has_instances=True,
	),
	_element(
		'left-premises-without-clock-out-count', 'staff-conduct',
		'Left-premises-without-clock-out count',
		'Times a staff member exited the building mid-shift without a '
		'logged clock-out.',
		[_CARD, _ALERT], models.Cadence.PER_EVENT, ['03', '15'],
		models.ValueKind.COUNT, 'events', 1, has_instances=True,
	),
	_element(
		'eating-drinking-at-station-count', 'staff-conduct',
		'Eating / drinking at station count',
		'Times food or drink was consumed at a prep or service station.',
		_ALERT_COUNT_TYPES, models.Cadence.PER_EVENT, ['05', '11', '12'],
		models.ValueKind.COUNT, 'events', 6, has_instances=True,
	),
	_element(
		'sleeping-on-duty-count', 'staff-conduct',
		'Sleeping / resting-on-duty count',
		'Times a staff member appeared to be asleep or resting during '
		'active hours.',
		_ALERT_COUNT_TYPES, models.Cadence.PER_EVENT, ['05', '11', '12'],
		models.ValueKind.COUNT, 'events', 1, has_instances=True,
	),
	_element(
		'unauthorised-visitor-count', 'staff-conduct',
		'Unauthorised-visitor count',
		'Times a non-employee was present in back-of-house areas.',
		[_CARD, _ALERT], models.Cadence.PER_EVENT, ['05', '13', '15'],
		models.ValueKind.COUNT, 'events', 2, has_instances=True,
	),
	_element(
		'horseplay-altercation-count', 'staff-conduct',
		'Horseplay / altercation count',
		'Times physical horseplay or a confrontation was detected among '
		'staff.',
		[_CARD, _ALERT], models.Cadence.REAL_TIME,
		['05', '11', '12', '13'],
		models.ValueKind.COUNT, 'events', 1, has_instances=True,
	),
]

ELEMENTS_BY_ID: dict[str, models.Element] = {
	element.id: element for element in ELEMENTS
}

SECTIONS: list[models.Section] = [
	models.Section(
		id=section_id,
		title=title,
		description=description,
		elements=[e for e in ELEMENTS if e.section_id == section_id],
	)
	for section_id, title, description in _SECTION_META
]

SECTIONS_BY_ID: dict[str, models.Section] = {
	section.id: section for section in SECTIONS
}

STAFF_ROSTER: list[dict[str, str]] = [
	{
		'id': 'emp-001',
		'name': 'Layla Haddad',
		'role': 'Shift lead',
		'shift_start': '07:00',
		'shift_end': '15:00',
	},
	{
		'id': 'emp-002',
		'name': 'Omar Nasser',
		'role': 'Cashier',
		'shift_start': '07:00',
		'shift_end': '15:00',
	},
	{
		'id': 'emp-003',
		'name': 'Rania Fakhoury',
		'role': 'Barista',
		'shift_start': '08:00',
		'shift_end': '16:00',
	},
	{
		'id': 'emp-004',
		'name': 'Yusuf Kader',
		'role': 'Line cook',
		'shift_start': '09:00',
		'shift_end': '17:00',
	},
	{
		'id': 'emp-005',
		'name': 'Dana Mroue',
		'role': 'Server',
		'shift_start': '12:00',
		'shift_end': '20:00',
	},
	{
		'id': 'emp-006',
		'name': 'Karim Salti',
		'role': 'Prep cook',
		'shift_start': '06:00',
		'shift_end': '14:00',
	},
]

CATALOGUE = models.Catalogue(
	cameras=CAMERAS, filters=FILTERS, sections=SECTIONS
)
