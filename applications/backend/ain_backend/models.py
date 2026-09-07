"""The wire contract, mirroring `frontend/src/api/types.ts`.

Field names are snake_case in Python and camelCase on the wire; the
alias generator is what bridges them, so a rename here is a rename
there. Optional fields are dropped rather than sent as null, matching
what the TypeScript's `?:` means.
"""

import enum
from typing import Literal

import pydantic
from pydantic import alias_generators

Point = dict[str, str | float]
"""One chart point: `x` plus one numeric key per series id."""


class Model(pydantic.BaseModel):
	"""Base for every response model."""

	model_config = pydantic.ConfigDict(
		alias_generator=alias_generators.to_camel,
		populate_by_name=True,
		serialize_by_alias=True,
	)


class ElementType(enum.StrEnum):
	"""Which renderer the frontend picks for an element."""

	KPI = 'kpi'
	STAT_GROUP = 'stat-group'
	LINE = 'line'
	HISTOGRAM = 'histogram'
	CAMERA_GRID = 'camera-grid'


class ElementKind(enum.StrEnum):
	"""Monitors track a value; alerts count occurrences."""

	MONITOR = 'monitor'
	ALERT = 'alert'


class UpdateCadence(enum.StrEnum):
	"""How often the frontend re-asks for an element."""

	REALTIME = 'realtime'
	EVENT = 'event'
	VISIT = 'visit'
	HOURLY = 'hourly'
	DAILY = 'daily'
	STATIC = 'static'


class Severity(enum.StrEnum):
	"""The backend's judgement, which the frontend maps to a colour."""

	OK = 'ok'
	INFO = 'info'
	WARN = 'warn'
	CRITICAL = 'critical'


class Direction(enum.StrEnum):
	"""Which glyph a delta pill carries."""

	UP = 'up'
	DOWN = 'down'
	FLAT = 'flat'


class Comparator(enum.StrEnum):
	"""The test an alert rule applies to its monitor."""

	ABOVE = 'above'
	BELOW = 'below'


class ElementDef(Model):
	"""One card in the layout."""

	id: str
	title: str
	description: str | None = None
	type: ElementType
	kind: ElementKind
	updates: UpdateCadence
	span: int | None = None
	cameras: list[str] | None = None
	drilldown: Literal['instances'] | None = None


class SectionDef(Model):
	"""One nav tab."""

	id: str
	title: str
	description: str | None = None
	view: Literal['grid', 'alerts'] | None = None
	elements: list[ElementDef]


class FilterOption(Model):
	"""One selectable value of a filter."""

	value: str
	label: str


class FilterDef(Model):
	"""A global control, owning one URL search parameter."""

	id: str
	label: str
	control: Literal['select', 'date-range'] | None = None
	options: list[FilterOption]
	default_value: str


class DashboardConfig(Model):
	"""The whole navigation and layout, localised."""

	branch_label: str
	today: str
	filters: list[FilterDef]
	sections: list[SectionDef]


class Delta(Model):
	"""A pre-formatted change, and whether it is good news."""

	label: str
	direction: Direction
	sentiment: Severity


class SeriesDef(Model):
	"""One line, bar stack or slice group in a chart."""

	id: str
	label: str
	color_index: int | None = None


class TrendPayload(Model):
	"""The compact chart a card carries under its numbers."""

	series: list[SeriesDef]
	points: list[Point]


class KpiPayload(Model):
	"""One headline number."""

	value: str
	unit: str | None = None
	delta: Delta | None = None
	severity: Severity | None = None
	trend: TrendPayload | None = None


class Stat(Model):
	"""One number inside a stat group."""

	id: str
	label: str
	value: str
	unit: str | None = None
	severity: Severity | None = None
	delta: Delta | None = None


class StatGroupPayload(Model):
	"""Several related numbers on one card."""

	stats: list[Stat]
	trend: TrendPayload | None = None


class SeriesPayload(Model):
	"""Line, bar, stacked-bar and histogram all draw this."""

	series: list[SeriesDef]
	points: list[Point]
	x_label: str | None = None
	y_label: str | None = None
	unit: str | None = None


class CameraFeed(Model):
	"""One tile of the camera grid."""

	id: str
	label: str
	zone: str
	status: Literal['online', 'offline']
	status_label: str
	stream_url: str | None = None
	thumbnail_url: str | None = None


class CameraGridPayload(Model):
	"""Every camera at the branch."""

	feeds: list[CameraFeed]


Payload = (
	KpiPayload
	| StatGroupPayload
	| SeriesPayload
	| CameraGridPayload
)


class ElementResponse(Model):
	"""One card's payload, discriminated by `type`."""

	element_id: str
	updated_at: str
	type: ElementType
	data: Payload


class Instance(Model):
	"""One occurrence behind an alert card."""

	id: str
	timestamp: str
	camera: str
	detail: str | None = None
	severity: Severity | None = None
	clip_url: str | None = None
	thumbnail_url: str | None = None


class InstanceLog(Model):
	"""The drilldown behind an element."""

	element_id: str
	title: str
	total: int
	instances: list[Instance]


class OverlayObject(Model):
	"""One detected object, in coordinates normalised against its frame."""

	track_id: int
	label: str
	xc: float
	yc: float
	w: float
	h: float


class OverlayFrame(Model):
	"""Every object seen at one instant."""

	ts: str
	objects: list[OverlayObject]


class OverlayResponse(Model):
	"""One window of detections for one camera.

	Passed through from the analytics service, but through these models
	rather than verbatim: that service speaks snake_case and this wire is
	camelCase, and `track_id` reaching the browser as-is is a box label
	reading "person undefined".
	"""

	camera: str
	start: str
	end: str
	frames: list[OverlayFrame]


class GeometryPart(Model):
	"""One camera's share of a zone or a counting line."""

	camera: str
	name: str | None = None
	points: list[list[float]]


class NamedGeometry(Model):
	"""A zone or a line, and the shapes that make it up."""

	name: str
	kind: Literal['polygon', 'line']
	# How many people the zone holds, when it declares one. Carried
	# because it is what a "passed 90%" alert is 90% OF - a reader who
	# wants to check that arithmetic should not need a second lookup.
	capacity: int | None = None
	parts: list[GeometryPart]


class ZonesResponse(Model):
	"""Every zone and line, as configured."""

	zones: list[NamedGeometry]
	lines: list[NamedGeometry]


class AlertMonitor(Model):
	"""A value an alert rule can be built on."""

	id: str
	label: str
	unit: str | None = None
	monthly_average: str
	monthly_average_value: float
	trend: TrendPayload | None = None


class AlertMonitorList(Model):
	"""Everything the alert builder can watch."""

	monitors: list[AlertMonitor]


class AlertRule(Model):
	"""A stored rule, localised at read time."""

	id: str
	monitor_id: str
	monitor_label: str
	comparator: Comparator
	threshold: float
	unit: str | None = None
	summary: str
	created_label: str
	# How the rule has actually done over the window in view. Absent when
	# there is no pipeline behind the monitor to evaluate it against, which
	# is different from "it has not fired": one is unknown, the other is
	# zero, and a card must not print them the same way.
	breaches: int | None = None
	status_label: str | None = None
	severity: Severity | None = None


class AlertRuleList(Model):
	"""Every rule in scope."""

	rules: list[AlertRule]


class AlertRuleDraft(Model):
	"""What the alert builder posts."""

	monitor_id: str
	comparator: Comparator
	threshold: float = pydantic.Field(ge=0)
