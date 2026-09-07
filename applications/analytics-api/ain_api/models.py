"""What every route accepts and returns, as types rather than as dicts.

A hand-built dict is a contract nobody can see. It does not appear in the
OpenAPI schema, so `ain_backend` - which is a different service, written
against this one - has nothing to generate from and nothing to validate
against; a renamed key ships green and breaks the dashboard at runtime.
These models are the contract, and FastAPI enforces them on the way out.

The house rule still holds: numbers and units, never a string a human
reads. `unit` fields say what the numbers are IN so the backend can format
them for Arabic; there are no severities, no sentences and no durations
pre-rendered as text anywhere in this file.
"""

import datetime
from typing import Literal

import pydantic

Comparator = Literal['above', 'below']
Basis = Literal['absolute', 'capacity', 'mean']
Metric = Literal['occupancy', 'footfall', 'dwell']
PpeKind = Literal['no-gloves', 'no-hair-cover', 'no-mask']


class Model(pydantic.BaseModel):
	"""Base for every response here."""

	model_config = pydantic.ConfigDict(extra='forbid')


class Health(Model):
	"""Whether the service can answer, and what it is holding."""

	status: Literal['ok', 'degraded']
	# Present only when degraded, so the reason travels with the 503
	# instead of only reaching the container log.
	detail: str | None = None
	latest_detection: datetime.datetime | None = None
	zones: list[str] = []
	lines: list[str] = []


class Camera(Model):
	"""One camera and whether anything is currently publishing it."""

	id: str
	stream: str
	description: str | None = None
	# None when MediaMTX itself could not be reached, which is not the same
	# as a camera that is down.
	live: bool | None = None
	recorded_from: datetime.datetime | None = None


class Cameras(Model):
	"""Every camera cameras.yml declares."""

	cameras: list[Camera]


class GeometryPart(Model):
	"""One camera's share of a shape, normalised 0..1 against its frame."""

	camera: str
	# None for an unnamed part, which is most of them. A zone spread over
	# two cameras has two anonymous parts; only the tables and the two
	# halves of a counting line are named, and there the name is what the
	# result is grouped by.
	name: str | None = None
	points: list[list[float]]


class NamedGeometry(Model):
	"""A zone or a counting line, with the polygons to draw it."""

	name: str
	kind: Literal['polygon', 'line']
	capacity: int | None = None
	parts: list[GeometryPart]


class Zones(Model):
	"""All the geometry, plus a token for detecting a stale edit."""

	# What the file looked like when this was read. Handed back on save so
	# a second editor cannot silently overwrite the first.
	version: str
	zones: list[NamedGeometry]
	lines: list[NamedGeometry]


class DrawnShape(Model):
	"""One shape the editor drew, in the editor's own vocabulary."""

	kind: Literal['polygon', 'line']
	name: str
	# For a zone part an optional label like `table-3`; for a line, which
	# half of the pair it is - `outer` or `inner`.
	part: str = ''
	capacity: int | None = None
	points: list[tuple[float, float]]


class DrawnCamera(Model):
	"""Everything one camera contributes, which is what a save replaces."""

	camera: str
	shapes: list[DrawnShape]
	# What `GET /zones` reported when the page loaded. Optional so curl
	# stays usable; checked whenever it is sent.
	version: str | None = None


class SavedGeometry(Model):
	"""What a camera contributes after a save."""

	zones: list[str]
	lines: list[str]


class Series(Model):
	"""Fields every bucketed answer carries."""

	start: datetime.datetime
	end: datetime.datetime
	cameras: list[str]
	interval_seconds: int


class OccupancyBucket(Model):
	"""One interval of an occupancy series."""

	ts: datetime.datetime
	mean: float
	peak: int
	# How much of the interval the window actually covers. The first and
	# last bucket are partial, and a plain average would weight a
	# one-second sliver like a five-minute interval.
	covered_seconds: float


class Occupancy(Series):
	"""How many people stood in a zone, over time."""

	zone: str
	unit: Literal['people'] = 'people'
	buckets: list[OccupancyBucket]
	# Instantaneous, not the trailing bucket's average: "how many are here
	# now" and "how many were here on average over five minutes" are
	# different questions and the card asks the first.
	latest: int
	mean: float
	peak: int


class DwellPart(Model):
	"""One named part of a zone - one table, say."""

	name: str
	visits: int
	mean_seconds: float
	median_seconds: float
	longest_seconds: float


class DwellBar(Model):
	"""One bar of the dwell histogram. `to` is None on the last."""

	from_seconds: int = pydantic.Field(alias='from')
	to_seconds: int | None = pydantic.Field(alias='to')
	visits: int

	model_config = pydantic.ConfigDict(populate_by_name=True, extra='forbid')


class DwellBucket(Model):
	"""One interval of the dwell-over-time series."""

	ts: datetime.datetime
	visits: int
	mean_seconds: float


class Dwell(Series):
	"""How long each visit to a zone lasted."""

	zone: str
	unit: Literal['seconds'] = 'seconds'
	visits: int
	mean_seconds: float
	parts: list[DwellPart]
	histogram: list[DwellBar]
	buckets: list[DwellBucket]


class FootfallBucket(Model):
	"""Crossings in one interval, by direction."""

	ts: datetime.datetime
	in_: int = pydantic.Field(alias='in')
	out: int

	model_config = pydantic.ConfigDict(populate_by_name=True, extra='forbid')


class Footfall(Series):
	"""People crossing a counting line, in each direction."""

	line: str
	unit: Literal['people'] = 'people'
	buckets: list[FootfallBucket]
	in_: int = pydantic.Field(alias='in')
	out: int

	model_config = pydantic.ConfigDict(populate_by_name=True, extra='forbid')


class Event(Model):
	"""One occurrence, carrying the shape it was raised on."""

	id: str
	type: str
	metric: str
	target: str
	start: datetime.datetime
	end: datetime.datetime
	peak_value: float
	cameras: list[str]
	geometry: dict | None = None

	# Each event kind adds its own measurements - a dwell event carries the
	# track and its length, a series event the run. They are numbers with
	# named units, not free text, and forbidding them here would mean a new
	# event kind could not be added without editing this file.
	model_config = pydantic.ConfigDict(extra='allow')


class Events(Model):
	"""Every occurrence in one window."""

	start: datetime.datetime
	end: datetime.datetime
	count: int
	events: list[Event]


class OverlayObject(Model):
	"""One box, normalised 0..1 and in centre form."""

	track_id: int
	label: str
	xc: float
	yc: float
	w: float
	h: float


class OverlayFrame(Model):
	"""Every box stored for one frame."""

	ts: datetime.datetime
	objects: list[OverlayObject]


class Overlay(Model):
	"""What the browser draws on top of the video."""

	camera: str
	start: datetime.datetime
	end: datetime.datetime
	frames: list[OverlayFrame]


class Ppe(Model):
	"""A PPE check that cannot be answered yet.

	`value` is null and never 0: a zero asserts "we watched and nobody
	violated the policy", which is a claim a person detector cannot make.
	"""

	value: None = None
	status: Literal['unavailable'] = 'unavailable'
	reason: str


class Clip(Model):
	"""Where to fetch the rendered clip for one event."""

	# A presigned link straight to the object store. The bytes do not come
	# back through this service, or through the backend behind it.
	url: str
	expires_at: datetime.datetime
	seconds: float
