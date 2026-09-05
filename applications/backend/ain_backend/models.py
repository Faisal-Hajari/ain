"""Response models shared by the catalogue and the dummy data layer.

The dashboard front end builds its cards, gauges and graphs from these
shapes, so they are the contract that survives when the real data
sources replace `ain_backend.dummy`.
"""

import datetime
import enum

import pydantic


class ElementType(enum.StrEnum):
	"""How the front end renders an element."""

	KPI_CARD = 'kpi_card'
	ALERT = 'alert'
	GRAPH_LINE = 'graph_line'
	GRAPH_BAR = 'graph_bar'
	GRAPH_DONUT = 'graph_donut'
	GRAPH_HISTOGRAM = 'graph_histogram'
	GAUGE = 'gauge'


class Cadence(enum.StrEnum):
	"""How often an element is refreshed upstream."""

	REAL_TIME = 'real_time'
	PER_EVENT = 'per_event'
	PER_VISIT = 'per_visit'
	HOURLY = 'hourly'
	DAILY = 'daily'


class ValueKind(enum.StrEnum):
	"""What an element's value means, and which payload it carries."""

	COUNT = 'count'
	PEOPLE = 'people'
	DURATION = 'duration'
	PERCENT = 'percent'
	CLOCK_TIME = 'clock_time'
	DISTRIBUTION = 'distribution'


class Placement(enum.StrEnum):
	"""Where a camera sits in the venue."""

	INDOOR = 'indoor'
	OUTDOOR = 'outdoor'
	BACK_OF_HOUSE = 'back_of_house'


class Camera(pydantic.BaseModel):
	"""A CCTV feed as installed at the branch."""

	id: str
	label: str
	coverage: str
	placement: Placement


class Element(pydantic.BaseModel):
	"""One catalogue entry: a KPI, an alert or a graph."""

	id: str
	section_id: str
	name: str
	measures: str
	types: list[ElementType]
	cadence: Cadence
	cameras: list[str]
	value_kind: ValueKind
	unit: str
	baseline: float
	has_instances: bool = False


class Section(pydantic.BaseModel):
	"""A catalogue chapter and the elements it groups."""

	id: str
	title: str
	description: str
	elements: list[Element]


class FilterOption(pydantic.BaseModel):
	"""One selectable value of a global filter."""

	id: str
	label: str
	label_ar: str


class FilterCatalogue(pydantic.BaseModel):
	"""The global controls that slice every panel."""

	branches: list[FilterOption]
	venue_types: list[FilterOption]
	date_ranges: list[FilterOption]
	languages: list[FilterOption]


class Catalogue(pydantic.BaseModel):
	"""Everything the front end needs to lay out the dashboard."""

	cameras: list[Camera]
	filters: FilterCatalogue
	sections: list[Section]


class TimeWindow(pydantic.BaseModel):
	"""The resolved date range a payload was computed over."""

	range_id: str
	start: datetime.datetime
	end: datetime.datetime
	bucket_seconds: int


class ScalarValue(pydantic.BaseModel):
	"""A single headline number plus its trend against the last window."""

	value: float
	unit: str
	delta_pct: float


class SeriesPoint(pydantic.BaseModel):
	"""One point of a trend line."""

	at: datetime.datetime
	value: float


class Bucket(pydantic.BaseModel):
	"""One bar, donut slice or histogram bin."""

	label: str
	value: float


class ElementData(pydantic.BaseModel):
	"""The payload behind a single dashboard element."""

	element_id: str
	value_kind: ValueKind
	unit: str
	generated_at: datetime.datetime
	window: TimeWindow
	scalar: ScalarValue | None = None
	series: list[SeriesPoint] | None = None
	buckets: list[Bucket] | None = None
	text: str | None = None


class Instance(pydantic.BaseModel):
	"""One occurrence behind an alert-count card."""

	id: str
	element_id: str
	occurred_at: datetime.datetime
	camera_id: str
	duration_seconds: float | None
	clip_url: str
	thumbnail_url: str


class Employee(pydantic.BaseModel):
	"""A rostered staff member and the day's derived timesheet."""

	id: str
	name: str
	role: str
	shift_start: str
	shift_end: str
	clock_in: str
	clock_out: str
	hours_worked: float
	late_arrival: bool
	ppe_adherence_pct: float
	no_gloves_count: int
	no_hair_cover_count: int
	no_mask_count: int
