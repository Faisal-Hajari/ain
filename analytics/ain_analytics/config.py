"""cameras.yml, parsed once, plus the SQL its geometry turns into.

Nothing else in this package knows what a zone is. A caller asks for
`zone=indoor` and gets back a predicate; the mapping from a zone name to
cameras and polygons stops here, which is what keeps `ain_backend` from
having to know which cameras compose a zone.
"""

import dataclasses
import functools
import os
import pathlib

import yaml

Point = tuple[float, float]

_DEFAULT_PATH = pathlib.Path(
	os.environ.get('AIN_CAMERAS_YML', '/app/cameras.yml')
)


class ConfigError(Exception):
	"""cameras.yml describes something that cannot work."""


class UnknownZoneError(KeyError):
	"""No zone or line in the config carries the requested name."""


@dataclasses.dataclass(frozen=True)
class Part:
	"""One camera's share of a zone.

	A zone is the sum of its parts. With no cross-camera re-identification
	two parts that see the same floor double-count whoever stands there,
	so the polygons are drawn disjoint and this stays a plain sum.
	"""

	camera: str
	points: tuple[Point, ...]
	name: str = ''

	@property
	def polygon_sql(self) -> str:
		"""The vertex list as a ClickHouse polygon literal."""
		vertices = ','.join(f'({x},{y})' for x, y in self.points)
		return f'[{vertices}]'

	@property
	def contains_sql(self) -> str:
		"""A predicate true for a detection standing in this part.

		Returns:
			SQL testing the FOOT point of the box, never its centre: on
			a wall-mounted camera the centre drifts across a boundary
			when somebody leans, and the foot point does not.
		"""
		return (
			f"(source_id = '{self.camera}' AND "
			f'pointInPolygon((xc, yc + h / 2), {self.polygon_sql}))'
		)


class NoCapacityError(KeyError):
	"""A zone was asked for a proportion of a capacity it does not declare."""


@dataclasses.dataclass(frozen=True)
class Zone:
	"""A named area, spread over one or more cameras."""

	name: str
	parts: tuple[Part, ...]
	# How many people the space holds. A judgement about the room, not a
	# measurement - it is what "occupancy passed 90%" is 90% of. None for a
	# zone where the question is meaningless, like the tables.
	capacity: int | None = None

	@property
	def cameras(self) -> tuple[str, ...]:
		"""Every camera this zone is seen by, in config order."""
		seen = dict.fromkeys(part.camera for part in self.parts)
		return tuple(seen)

	@property
	def contains_sql(self) -> str:
		"""A predicate true for a detection standing anywhere in it."""
		return '(' + ' OR '.join(part.contains_sql for part in self.parts) + ')'

	@property
	def cameras_sql(self) -> str:
		"""A predicate narrowing a scan to this zone's cameras.

		Returns:
			SQL that is redundant with `contains_sql` and there for
			speed. `source_id` is the first column of the table's sort
			key, so this prunes whole parts; without it a zone on one
			camera still evaluates pointInPolygon against every row of
			every other one, which over thirty days is a full scan of the
			retention window.
		"""
		ids = ', '.join(f"'{camera}'" for camera in self.cameras)
		return f'source_id IN ({ids})'

	def part_name_sql(self) -> str:
		"""An expression naming which part a detection stands in.

		Returns:
			SQL evaluating to the part's name, or `''` for a detection
			outside every part. Unnamed parts answer with the zone name,
			so a zone that is not subdivided still groups.
		"""
		branches = []
		for index, part in enumerate(self.parts):
			label = part.name or f'{self.name}-{index + 1}'
			branches.append(f"{part.contains_sql}, '{label}'")
		return f'multiIf({", ".join(branches)}, \'\')'

	def proportion(self, fraction: float) -> float:
		"""Turns "90% full" into a number of people.

		Args:
			fraction: The share of capacity, 0.9 for ninety percent.

		Returns:
			The threshold in people.

		Raises:
			NoCapacityError: This zone declares no capacity, so there is
				nothing for a percentage to be a percentage of. Guessing
				one would put a made-up number behind an alert.
		"""
		if self.capacity is None:
			raise NoCapacityError(self.name)
		return self.capacity * fraction

	def geometry(self) -> dict:
		"""The shape to draw for an event raised on this zone."""
		return {
			'kind': 'polygon',
			'capacity': self.capacity,
			'parts': [
				{
					'camera': part.camera,
					'name': part.name or None,
					'points': [list(point) for point in part.points],
				}
				for part in self.parts
			],
		}


@dataclasses.dataclass(frozen=True)
class Line:
	"""A counting line, which is really two parallel lines.

	One line and a jittering bounding box produce phantom crossings all
	day. Requiring both to be crossed, in order, throws those away, and
	which one is crossed first is what gives the crossing a direction.
	"""

	name: str
	camera: str
	outer: tuple[Point, Point]
	inner: tuple[Point, Point]

	def geometry(self) -> dict:
		"""The shape to draw for an event raised on this line."""
		return {
			'kind': 'line',
			'parts': [
				{
					'camera': self.camera,
					'name': side,
					'points': [list(point) for point in pair],
				}
				for side, pair in (('outer', self.outer), ('inner', self.inner))
			],
		}


@dataclasses.dataclass(frozen=True)
class Config:
	"""Everything cameras.yml declares."""

	cameras: dict[str, dict]
	zones: dict[str, Zone]
	lines: dict[str, Line]
	kafka_brokers: str
	kafka_topic: str

	def zone(self, name: str) -> Zone:
		"""Looks up a zone.

		Args:
			name: The zone name from the query string.

		Returns:
			The zone.

		Raises:
			UnknownZoneError: No zone carries that name.
		"""
		if name not in self.zones:
			raise UnknownZoneError(name)
		return self.zones[name]

	def line(self, name: str) -> Line:
		"""Looks up a counting line.

		Args:
			name: The line name from the query string.

		Returns:
			The line.

		Raises:
			UnknownZoneError: No line carries that name.
		"""
		if name not in self.lines:
			raise UnknownZoneError(name)
		return self.lines[name]

	def stream(self, camera: str) -> str | None:
		"""Returns the MediaMTX path a camera is published on."""
		entry = self.cameras.get(camera)
		return entry.get('stream') if entry else None


def _segments_cross(a: Point, b: Point, c: Point, d: Point) -> bool:
	"""Reports whether segments a-b and c-d properly intersect."""

	def side(p: Point, q: Point, r: Point) -> float:
		return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])

	d1, d2 = side(c, d, a), side(c, d, b)
	d3, d4 = side(a, b, c), side(a, b, d)
	return ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0))


def _check_simple(where: str, points: tuple[Point, ...]) -> None:
	"""Rejects a polygon whose edges cross.

	Args:
		where: What is being checked, for the error message.
		points: The vertices, in order.

	Raises:
		ConfigError: Two non-adjacent edges cross.

	A hand-written vertex list very easily describes a bow-tie, and a
	self-intersecting polygon does not fail - `pointInPolygon` simply
	answers nonsense for half of it. Checked here, at load, so the
	service refuses to start on one rather than reporting occupancy
	nobody can explain.
	"""
	count = len(points)
	edges = [(points[i], points[(i + 1) % count]) for i in range(count)]
	for i, (a, b) in enumerate(edges):
		for j, (c, d) in enumerate(edges):
			# Adjacent edges share a vertex and always "touch".
			if j <= i or (j - i) % count <= 1 or (i - j) % count <= 1:
				continue
			if _segments_cross(a, b, c, d):
				raise ConfigError(
					f'{where}: edges {i} and {j} cross - the vertices are '
					'out of order and this polygon is a bow-tie'
				)


def _points(raw: object, where: str) -> tuple[Point, ...]:
	"""Converts a config point list, rejecting anything unusable.

	Args:
		raw: The value read from YAML.
		where: What is being read, for the error message.

	Returns:
		The points as tuples.

	Raises:
		ConfigError: A point is malformed or outside 0..1.
	"""
	if not isinstance(raw, list) or len(raw) < 2:
		raise ConfigError(f'{where}: needs at least two points')
	points = []
	for point in raw:
		if not isinstance(point, list) or len(point) != 2:
			raise ConfigError(f'{where}: {point!r} is not an [x, y] pair')
		x, y = float(point[0]), float(point[1])
		if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
			raise ConfigError(
				f'{where}: {point!r} is outside 0..1 - coordinates are '
				'normalised against the frame, not pixels'
			)
		points.append((x, y))
	return tuple(points)


def load(path: pathlib.Path | None = None) -> Config:
	"""Reads cameras.yml.

	Args:
		path: Where to read it from. Defaults to `$AIN_CAMERAS_YML`.

	Returns:
		The parsed config.

	Raises:
		ConfigError: A zone or line names an unknown camera, or its
			points are unusable.
	"""
	path = path or _DEFAULT_PATH
	document = yaml.safe_load(path.read_text())
	cameras = document.get('cameras') or {}
	if not cameras:
		raise ConfigError(f'{path}: no cameras')

	zones = {}
	for name, raw_zone in (document.get('zones') or {}).items():
		# A zone is `{capacity?, parts: [...]}`. A bare list is the older
		# shape and still reads, because a zone without a capacity is a
		# perfectly good zone - it just cannot be alerted on proportionally.
		if isinstance(raw_zone, list):
			raw_parts, capacity = raw_zone, None
		else:
			raw_parts = raw_zone.get('parts') or []
			capacity = raw_zone.get('capacity')
		if capacity is not None and (
			not isinstance(capacity, int) or capacity <= 0
		):
			raise ConfigError(
				f'zone {name}: capacity {capacity!r} is not a positive '
				'number of people'
			)
		parts = []
		for index, raw in enumerate(raw_parts):
			where = f'zone {name}[{index}]'
			camera = raw.get('camera')
			if camera not in cameras:
				raise ConfigError(f'{where}: unknown camera {camera!r}')
			points = _points(raw.get('points'), where)
			if len(points) < 3:
				raise ConfigError(f'{where}: a polygon needs three points')
			_check_simple(where, points)
			parts.append(
				Part(camera=camera, points=points, name=raw.get('name', ''))
			)
		if not parts:
			raise ConfigError(f'zone {name}: no parts')
		zones[name] = Zone(
			name=name, parts=tuple(parts), capacity=capacity
		)

	lines = {}
	for name, raw in (document.get('lines') or {}).items():
		camera = raw.get('camera')
		if camera not in cameras:
			raise ConfigError(f'line {name}: unknown camera {camera!r}')
		sides = {}
		for side in ('outer', 'inner'):
			if side not in raw:
				raise ConfigError(
					f'line {name}: no {side} line. Footfall needs two '
					'parallel lines crossed in order; one line and a '
					'jittering box produce phantom crossings.'
				)
			points = _points(raw[side], f'line {name}.{side}')
			if len(points) != 2:
				raise ConfigError(f'line {name}.{side}: needs exactly two points')
			sides[side] = points
		lines[name] = Line(
			name=name,
			camera=camera,
			outer=sides['outer'],
			inner=sides['inner'],
		)

	kafka = document.get('kafka') or {}
	return Config(
		cameras=cameras,
		zones=zones,
		lines=lines,
		kafka_brokers=os.environ.get(
			'KAFKA_BROKERS', kafka.get('brokers', 'kafka:9092')
		),
		kafka_topic=os.environ.get(
			'KAFKA_TOPIC', kafka.get('topic', 'ain.people.raw')
		),
	)


@functools.cache
def get() -> Config:
	"""Returns the process-wide config, read once."""
	return load()
